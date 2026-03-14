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
    if os.path.exists('/root/.mysql_password'):
        with open('/root/.mysql_password', 'r') as f:
            password = f.read().strip()

    try:
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
            connection = pymysql.connect(
                host='localhost',
                user='root',
                cursorclass=pymysql.cursors.DictCursor
            )
            return connection
        except pymysql.MySQLError as e2:
            return None

def get_databases():
    conn = get_mysql_connection()
    if not conn: return []

    try:
        with conn.cursor() as cursor:
            cursor.execute("SHOW DATABASES")
            dbs = cursor.fetchall()
            return [db['Database'] for db in dbs if db['Database'] not in ('information_schema', 'mysql', 'performance_schema', 'sys')]
    finally:
        if conn:
            conn.close()

def create_database(db_name, db_user, db_pass):
    conn = get_mysql_connection()
    if not conn: return False, "Could not connect to database server."

    try:
        with conn.cursor() as cursor:
            # Escape identifiers by duplicating backticks
            db_name = db_name.replace('`', '``')
            db_user = db_user.replace('`', '``')
            db_pass = pymysql.converters.escape_string(db_pass)

            cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{db_name}`")
            cursor.execute(f"CREATE USER IF NOT EXISTS '{db_user}'@'localhost' IDENTIFIED BY '{db_pass}'")
            cursor.execute(f"GRANT ALL PRIVILEGES ON `{db_name}`.* TO '{db_user}'@'localhost'")
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

    try:
        with conn.cursor() as cursor:
            db_name = db_name.replace('`', '``')
            cursor.execute(f"DROP DATABASE IF EXISTS `{db_name}`")
        conn.commit()
        return True, "Database deleted successfully."
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
    config_path = '/etc/phpmyadmin/config.inc.php'
    if not os.path.exists(config_path):
        return False, "phpMyAdmin is not installed or config not found."

    try:
        with open(config_path, 'r') as f:
            lines = f.readlines()

        # Check if signon is already configured
        already_configured = False
        for line in lines:
            if 'PMA_Signon' in line:
                already_configured = True
                break

        if not already_configured:
            modified = False
            with open(config_path, 'w') as f:
                for line in lines:
                    if 'auth_type' in line and 'cookie' in line:
                        f.write(line.replace('cookie', 'signon').lstrip('//').lstrip('#'))
                        modified = True
                    else:
                        f.write(line)

                if not modified:
                    f.write("\n$cfg['Servers'][$i]['auth_type'] = 'signon';\n")

                f.write("\n$cfg['Servers'][$i]['SignonSession'] = 'PMA_Signon';\n")
                f.write("$cfg['Servers'][$i]['SignonURL'] = '/phpmyadmin/phpmyadmin_login.php';\n")
                f.write("$cfg['Servers'][$i]['LogoutURL'] = '/';\n")

        pma_login_script = """<?php
session_name('PMA_Signon');
session_start();

if (isset($_GET['token']) && preg_match('/^[a-f0-9]{32}$/', $_GET['token'])) {
    $token = $_GET['token'];
    $token_file = "/var/lib/cpanel_tokens/pma_{$token}.txt";

    if (file_exists($token_file)) {
        // Read the file content which contains the password securely
        $db_password = trim(file_get_contents($token_file));

        // Log them in
        $_SESSION['PMA_single_signon_user'] = 'root';
        $_SESSION['PMA_single_signon_password'] = $db_password;

        // Invalidate token immediately
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
