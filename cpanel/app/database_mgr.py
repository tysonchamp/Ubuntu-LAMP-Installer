import pymysql
import os
import secrets
import subprocess
import crypt

def get_mysql_connection():
    """
    Attempts to connect to MySQL as root.
    It checks common locations for the root password created by the stack installer.
    """
    password = ''
    pass_file = '/var/lib/lite-cpanel/.passwords'
    if os.path.exists(pass_file):
        with open(pass_file, 'r') as f:
            for line in f:
                if line.startswith('MySQL Root Password:'):
                    password = line.split(':', 1)[1].strip()
                    break
            
    sock_paths = ['/var/run/mysqld/mysqld.sock', '/tmp/mysql.sock']
    sock = None
    for s in sock_paths:
        if os.path.exists(s):
            sock = s
            break

    try:
        if sock:
            connection = pymysql.connect(
                unix_socket=sock,
                user='root',
                password=password,
                cursorclass=pymysql.cursors.DictCursor
            )
        else:
            connection = pymysql.connect(
                host='localhost',
                user='root',
                password=password,
                cursorclass=pymysql.cursors.DictCursor
            )
        return connection
    except pymysql.MySQLError as e:
        # Maybe passwordless root login is enabled via unix_socket
        try:
            if sock:
                connection = pymysql.connect(
                    unix_socket=sock,
                    user='root',
                    cursorclass=pymysql.cursors.DictCursor
                )
            else:
                connection = pymysql.connect(
                    host='localhost',
                    user='root',
                    cursorclass=pymysql.cursors.DictCursor
                )
            return connection
        except pymysql.MySQLError as e2:
            return None

def get_databases():
    """Returns a list of user databases (excluding system DBs)."""
    conn = get_mysql_connection()
    if not conn: return []
    try:
        with conn.cursor() as cursor:
            cursor.execute("SHOW DATABASES")
            dbs = cursor.fetchall()
            return [db['Database'] for db in dbs if db['Database'] not in ('information_schema', 'mysql', 'performance_schema', 'sys')]
    finally:
        conn.close()

def get_database_details():
    """
    Returns a list of dicts with db name, plus all users and their allowed hosts that
    have privileges on each database.
    """
    conn = get_mysql_connection()
    if not conn: return []
    try:
        with conn.cursor() as cursor:
            cursor.execute("SHOW DATABASES")
            raw_dbs = [db['Database'] for db in cursor.fetchall()
                       if db['Database'] not in ('information_schema', 'mysql', 'performance_schema', 'sys')]

            result = []
            for db in raw_dbs:
                db_escaped = db.replace('`', '``')
                cursor.execute(
                    "SELECT User, Host FROM mysql.db WHERE Db = %s ORDER BY User, Host",
                    (db,)
                )
                users = cursor.fetchall()  # [{User:..., Host:...}, ...]
                result.append({'name': db, 'users': users})
            return result
    finally:
        conn.close()

def change_user_password(db_user, host, new_password):
    conn = get_mysql_connection()
    if not conn: return False, "Could not connect to database server."
    try:
        with conn.cursor() as cursor:
            # Use %s parameterized query for the password — pymysql handles all escaping safely.
            # Manually single-quote-escape user and host (identifiers, not values).
            user_esc = db_user.replace("'", "''")
            host_esc = host.replace("'", "''")
            cursor.execute(
                f"ALTER USER '{user_esc}'@'{host_esc}' IDENTIFIED BY %s",
                (new_password,)
            )
            cursor.execute("FLUSH PRIVILEGES")
        conn.commit()
        return True, f"Password updated for {db_user}@{host}."
    except pymysql.MySQLError as e:
        return False, f"Error: {str(e)}"
    finally:
        conn.close()

def update_user_host(db_name, db_user, old_host, new_host):
    """
    Changes a user's host, effectively toggling between 'localhost' (local-only)
    and '%' (remote access allowed).
    """
    conn = get_mysql_connection()
    if not conn: return False, "Could not connect to database server."
    try:
        with conn.cursor() as cursor:
            db_escaped  = db_name.replace('`', '``')
            new_host_esc = pymysql.converters.escape_string(new_host)
            old_host_esc = pymysql.converters.escape_string(old_host)
            user_esc     = pymysql.converters.escape_string(db_user)

            # Rename the user
            cursor.execute(
                f"RENAME USER '{user_esc}'@'{old_host_esc}' TO '{user_esc}'@'{new_host_esc}'"
            )
            cursor.execute("FLUSH PRIVILEGES")
        conn.commit()
        label = 'remote (%)' if new_host == '%' else 'local (localhost)'
        return True, f"{db_user} host updated to {label}."
    except pymysql.MySQLError as e:
        return False, f"Error: {str(e)}"
    finally:
        conn.close()

def create_database(db_name, db_user, db_pass):
    conn = get_mysql_connection()
    if not conn: return False, "Could not connect to database server."

    try:
        with conn.cursor() as cursor:
            # Escape identifiers (db_name, db_user) by quoting backticks.
            # Use %s parameterized query for the password.
            db_name_esc = db_name.replace('`', '``')
            db_user_esc = db_user.replace('`', '``')
            user_host   = db_user.replace("'", "''")

            cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{db_name_esc}`")
            cursor.execute(
                f"CREATE USER IF NOT EXISTS '{user_host}'@'localhost' IDENTIFIED BY %s",
                (db_pass,)
            )
            # Force update the password in case the user already existed
            cursor.execute(
                f"ALTER USER '{user_host}'@'localhost' IDENTIFIED BY %s",
                (db_pass,)
            )
            cursor.execute(f"GRANT ALL PRIVILEGES ON `{db_name_esc}`.* TO '{user_host}'@'localhost'")
            cursor.execute("FLUSH PRIVILEGES")
        conn.commit()
        return True, "Database and user created successfully."
    except pymysql.MySQLError as e:
        return False, f"Database error: {str(e)}"
    finally:
        if conn:
            conn.close()

def delete_database(db_name):
    conn = get_mysql_connection()
    if not conn: return False, "Could not connect to database server."

    dropped_users = []
    try:
        with conn.cursor() as cursor:
            # Find all users that have privileges on this specific database
            cursor.execute(
                "SELECT User, Host FROM mysql.db WHERE Db = %s",
                (db_name,)
            )
            affected_users = cursor.fetchall()  # [{User: ..., Host: ...}, ...]

            for u in affected_users:
                user_esc = u['User'].replace("'", "''")
                host_esc = u['Host'].replace("'", "''")

                # Check if this user has grants on ANY other database
                cursor.execute(
                    "SELECT COUNT(*) as cnt FROM mysql.db WHERE User = %s AND Host = %s AND Db != %s",
                    (u['User'], u['Host'], db_name)
                )
                row = cursor.fetchone()
                other_db_count = row['cnt'] if row else 0

                if other_db_count == 0:
                    # User is exclusive to this DB — safe to fully drop them
                    cursor.execute(f"DROP USER IF EXISTS '{user_esc}'@'{host_esc}'")
                    dropped_users.append(f"{u['User']}@{u['Host']}")
                else:
                    # User has other databases — only revoke privileges on this DB
                    db_esc = db_name.replace('`', '``')
                    cursor.execute(
                        f"REVOKE ALL PRIVILEGES ON `{db_esc}`.* FROM '{user_esc}'@'{host_esc}'"
                    )

            db_esc = db_name.replace('`', '``')
            cursor.execute(f"DROP DATABASE IF EXISTS `{db_esc}`")
            cursor.execute("FLUSH PRIVILEGES")
        conn.commit()

        msg = "Database deleted successfully."
        if dropped_users:
            msg += f" Removed users: {', '.join(dropped_users)}."
        return True, msg
    except pymysql.MySQLError as e:
        return False, f"Database error: {str(e)}"
    finally:
        if conn:
            conn.close()

def setup_phpmyadmin_signon():
    """
    Modifies phpMyAdmin config to allow signon.
    Returns the auto-login URL.
    """
    conf_d_dir = '/etc/phpmyadmin/conf.d'
    if not os.path.exists('/etc/phpmyadmin'):
        return False, "phpMyAdmin is not installed."

    if not os.path.exists(conf_d_dir):
        try:
            os.makedirs(conf_d_dir)
        except Exception:
            pass

    try:
        signon_conf = "<?php\n"
        signon_conf += "$cfg['Servers'][1]['auth_type'] = 'signon';\n"
        signon_conf += "$cfg['Servers'][1]['SignonSession'] = 'PMA_Signon';\n"
        signon_conf += "$cfg['Servers'][1]['SignonURL'] = '/phpmyadmin/phpmyadmin_login.php';\n"
        signon_conf += "$cfg['Servers'][1]['LogoutURL'] = '/';\n"
        signon_conf += "?>\n"
        
        with open(os.path.join(conf_d_dir, 'cpanel_signon.php'), 'w') as f:
            f.write(signon_conf)

        pma_login_script = """<?php
session_name('PMA_Signon');
session_start();

if (isset($_GET['token']) && preg_match('/^[a-f0-9]{32}$/', $_GET['token'])) {
    $token = $_GET['token'];
    $token_file = "/var/lib/cpanel_tokens/pma_{$token}.txt";

    if (file_exists($token_file)) {
        $contents = trim(file_get_contents($token_file));
        // Format: "user:password" — password may be empty
        $parts = explode(':', $contents, 2);
        $db_user = isset($parts[0]) ? $parts[0] : 'root';
        $db_pass = isset($parts[1]) ? $parts[1] : '';

        $_SESSION['PMA_single_signon_user'] = $db_user;
        $_SESSION['PMA_single_signon_password'] = $db_pass;

        unlink($token_file);

        header('Location: /phpmyadmin/index.php');
        die();
    }
}

echo "Invalid or expired login token.";
?>"""
        with open('/usr/share/phpmyadmin/phpmyadmin_login.php', 'w') as f2:
            f2.write(pma_login_script)

        # Ensure PHP can read the script
        os.chmod('/usr/share/phpmyadmin/phpmyadmin_login.php', 0o644)

        return True, "Signon configured."
    except Exception as e:
        return False, f"Error configuring phpMyAdmin: {str(e)}"
