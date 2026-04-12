from flask import Flask, render_template, request, redirect, url_for, session, flash
import os

# Ensure standard bin directories are available in the PATH for all subprocess calls
os.environ["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:" + os.environ.get("PATH", "")

import psutil
from auth import check_system_password, login_required
from dotenv import load_dotenv
from flask_wtf.csrf import CSRFProtect

load_dotenv()

app = Flask(__name__)
csrf = CSRFProtect(app)
# Persist secret key across restarts so sessions are not invalidated.
# Falls back to a random key if not in env, but logs a warning.
app.secret_key = os.environ.get('FLASK_SECRET_KEY')
if not app.secret_key:
    import logging
    logging.warning("No FLASK_SECRET_KEY set in environment. Using a random key. Sessions will invalidate on restart.")
    app.secret_key = os.urandom(24)

@app.route('/')
def index():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return redirect(url_for('dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('logged_in'):
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if check_system_password(username, password):
            session['logged_in'] = True
            session['username'] = username
            flash('Logged in successfully!', 'success')

            # Prevent open redirects
            next_page = request.args.get('next')
            if not next_page or not next_page.startswith('/'):
                next_page = url_for('dashboard')
            return redirect(next_page)
        else:
            flash('Invalid username or password', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    session.pop('username', None)
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():

    # Get basic system stats
    cpu_usage = psutil.cpu_percent(interval=1)
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage('/')

    stats = {
        'cpu': cpu_usage,
        'ram_total': round(ram.total / (1024**3), 2),
        'ram_used': round(ram.used / (1024**3), 2),
        'ram_percent': ram.percent,
        'disk_total': round(disk.total / (1024**3), 2),
        'disk_used': round(disk.used / (1024**3), 2),
        'disk_percent': disk.percent
    }

    return render_template('dashboard.html', stats=stats)

from domains_mgr import get_virtual_hosts, add_virtual_host, toggle_virtual_host

@app.route('/domains', methods=['GET', 'POST'])
@login_required
def domains():
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'add':
            domain = request.form.get('domain')
            success, message = add_virtual_host(domain)
            if success:
                flash(message, 'success')
            else:
                flash(message, 'danger')

        elif action == 'toggle':
            domain = request.form.get('domain')
            enable_str = request.form.get('enable')
            enable = enable_str.lower() == 'true'

            success, message = toggle_virtual_host(domain, enable)
            if success:
                flash(message, 'success')
            else:
                flash(message, 'danger')

        elif action == 'ssl_generate':
            domain = request.form.get('domain')
            servers = request.form.get('servers', '')
            import subprocess
            try:
                # Automatically choose plugin based on active servers
                plugin = '--nginx' if 'Nginx' in servers and 'Apache' not in servers else '--apache'
                cmd = ['certbot', plugin, '-d', domain, '-d', f'www.{domain}', '--non-interactive', '--agree-tos', '-m', f'admin@{domain}']
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0:
                    flash(f"SSL Certificate generated successfully for {domain}!", 'success')
                else:
                    flash(f"SSL Generation failed: {result.stderr}", 'danger')
            except Exception as e:
                flash(f"Error during SSL setup: {str(e)}", 'danger')

        elif action == 'ssl_renew':
            import subprocess
            try:
                result = subprocess.run(['certbot', 'renew', '--non-interactive'], capture_output=True, text=True)
                if result.returncode == 0:
                    flash("Certificates renewed successfully. " + result.stdout, 'success')
                else:
                    flash(f"Renewal issue: {result.stderr}", 'danger')
            except Exception as e:
                flash(f"Error during renewal: {str(e)}", 'danger')

        return redirect(url_for('domains'))

    vhosts = get_virtual_hosts()
    return render_template('domains.html', vhosts=vhosts)

@app.route('/domains/logs/<domain>')
@login_required
def domain_logs(domain):
    """Page view: discover all log files for the given domain."""
    available_logs = {}

    # Domain-specific Apache log files
    for suffix, label in [('_error.log', 'Apache Error'), ('_access.log', 'Apache Access'),
                          ('_ssl_error.log', 'Apache SSL Error'), ('_ssl_access.log', 'Apache SSL Access')]:
        path = f'/var/log/apache2/{domain}{suffix}'
        if os.path.exists(path):
            available_logs[label] = path

    # Global Apache fallback — traffic from vhosts without dedicated log lines lands here
    for path, label in [('/var/log/apache2/error.log',  'Apache Error (Global)'),
                        ('/var/log/apache2/access.log', 'Apache Access (Global)')]:
        if os.path.exists(path):
            available_logs[label] = f'__apache_filter__:{path}'

    # Domain-specific Nginx log files
    for suffix, label in [('_error.log', 'Nginx Error'), ('_access.log', 'Nginx Access')]:
        path = f'/var/log/nginx/{domain}{suffix}'
        if os.path.exists(path):
            available_logs[label] = path

    # Global Nginx fallback — always include, filtered by domain
    for path, label in [('/var/log/nginx/error.log',  'Nginx Error (Global, filtered)'),
                        ('/var/log/nginx/access.log', 'Nginx Access (Global, filtered)')]:
        if os.path.exists(path):
            available_logs[label] = f'__nginx_filter__:{path}'

    return render_template('domain_logs.html', domain=domain, available_logs=available_logs)


@app.route('/domains/logs/<domain>/fetch')
@login_required
def domain_logs_fetch(domain):
    """JSON API: return the last N lines of a given log file for this domain."""
    from flask import jsonify
    import subprocess

    log_key  = request.args.get('log', '')
    lines    = request.args.get('lines', '100')

    # Rebuild available_logs the same way as domain_logs() to validate the path
    available_logs = {}
    for suffix, label in [('_error.log', 'Apache Error'), ('_access.log', 'Apache Access'),
                          ('_ssl_error.log', 'Apache SSL Error'), ('_ssl_access.log', 'Apache SSL Access')]:
        path = f'/var/log/apache2/{domain}{suffix}'
        if os.path.exists(path):
            available_logs[label] = path
    for path, label in [('/var/log/apache2/error.log',  'Apache Error (Global)'),
                        ('/var/log/apache2/access.log', 'Apache Access (Global)')]:
        if os.path.exists(path):
            available_logs[label] = f'__apache_filter__:{path}'
    for suffix, label in [('_error.log', 'Nginx Error'), ('_access.log', 'Nginx Access')]:
        path = f'/var/log/nginx/{domain}{suffix}'
        if os.path.exists(path):
            available_logs[label] = path
    for path, label in [('/var/log/nginx/error.log',  'Nginx Error (Global, filtered)'),
                        ('/var/log/nginx/access.log', 'Nginx Access (Global, filtered)')]:
        if os.path.exists(path):
            available_logs[label] = f'__nginx_filter__:{path}'

    if log_key not in available_logs:
        return jsonify({'error': 'Invalid log file selected.'}), 400

    try:
        lines_int = max(1, min(int(lines), 5000))
    except ValueError:
        lines_int = 100

    path = available_logs[log_key]
    try:
        if path.startswith('__nginx_filter__:'):
            real_path = path.split(':', 1)[1]
            res = subprocess.run(
                f'grep "{domain}" {real_path} | tail -n {lines_int}',
                shell=True, capture_output=True, text=True
            )
            display_path = real_path
        elif path.startswith('__apache_filter__:'):
            real_path = path.split(':', 1)[1]
            res = subprocess.run(
                f'grep "{domain}" {real_path} | tail -n {lines_int}',
                shell=True, capture_output=True, text=True
            )
            display_path = real_path
        else:
            res = subprocess.run(['tail', '-n', str(lines_int), path], capture_output=True, text=True)
            display_path = path

        content = res.stdout if res.stdout.strip() else '(Log is empty or has no entries yet.)'
        return jsonify({'content': content, 'path': display_path})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

from database_mgr import (get_databases, get_database_details, create_database,
                           delete_database, setup_phpmyadmin_signon,
                           change_user_password, update_user_host)

@app.route('/databases', methods=['GET', 'POST'])
@login_required
def databases():
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'create':
            db_name = request.form.get('db_name')
            db_user = request.form.get('db_user')
            db_pass = request.form.get('db_pass')
            success, message = create_database(db_name, db_user, db_pass)
            flash(message, 'success' if success else 'danger')

        elif action == 'delete':
            db_name = request.form.get('db_name')
            success, message = delete_database(db_name)
            flash(message, 'success' if success else 'danger')

        elif action == 'change_password':
            db_user = request.form.get('db_user')
            host    = request.form.get('host')
            new_pw  = request.form.get('new_password')
            success, message = change_user_password(db_user, host, new_pw)
            flash(message, 'success' if success else 'danger')

        elif action == 'update_host':
            db_name  = request.form.get('db_name')
            db_user  = request.form.get('db_user')
            old_host = request.form.get('old_host')
            new_host = request.form.get('new_host')
            success, message = update_user_host(db_name, db_user, old_host, new_host)
            flash(message, 'success' if success else 'danger')

        return redirect(url_for('databases'))

    db_details = get_database_details()
    return render_template('databases.html', db_details=db_details)

@app.route('/phpmyadmin-login')
@login_required
def phpmyadmin_login():
    success, msg = setup_phpmyadmin_signon()
    if not success:
        flash(f"phpMyAdmin signon setup failed: {msg}", "danger")
        return redirect(url_for('dashboard'))


    # In a real environment, sharing credentials between Python and PHP should use
    # a secure backing store (e.g. database, redis, memcached).
    # Since we lack those consistently, and we know we're on the same server,
    # we'll create a restricted directory that the webserver user can read.

    import secrets
    import grp
    import pwd
    token = secrets.token_hex(16)

    # Secure temporary directory for exchanging tokens
    token_dir = '/var/lib/cpanel_tokens'
    if not os.path.exists(token_dir):
        os.makedirs(token_dir, mode=0o750)
        # Ensure www-data can read/execute the dir
        try:
            www_data_gid = grp.getgrnam('www-data').gr_gid
            os.chown(token_dir, -1, www_data_gid)
        except KeyError:
            pass # fallback if www-data doesn't exist

    token_file = os.path.join(token_dir, f'pma_{token}.txt')

    mysql_pass = ''
    pass_file = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../scripts/.passwords'))
    if os.path.exists(pass_file):
        with open(pass_file, 'r') as f:
            for line in f:
                if line.startswith('MySQL Root Password:'):
                    mysql_pass = line.split(':', 1)[1].strip()
                    break

    # Write only readable by root and www-data group
    # 0o640: rw-r-----
    with open(token_file, 'w') as f:
        f.write(mysql_pass)

    try:
        www_data_gid = grp.getgrnam('www-data').gr_gid
        os.chown(token_file, -1, www_data_gid)
        os.chmod(token_file, 0o640)
    except KeyError:
        os.chmod(token_file, 0o644) # fallback

    # Redirect to the phpMyAdmin login handler we created (at the correct alias)
    host = request.host.split(':')[0]
    return redirect(f"http://{host}/phpmyadmin/phpmyadmin_login.php?token={token}")

from ftp_mgr import check_pureftpd_installed, get_ftp_users, create_ftp_user, delete_ftp_user, change_ftp_password

@app.route('/ftp', methods=['GET', 'POST'])
@login_required
def ftp():
    ftp_installed = check_pureftpd_installed()

    if request.method == 'POST' and ftp_installed:
        action = request.form.get('action')

        if action == 'create':
            username = request.form.get('username')
            password = request.form.get('password')
            raw_directory = request.form.get('directory')

            # Secure path resolution to prevent traversal
            base_dir = '/var/www'
            # If they didn't include the base, add it
            if not raw_directory.startswith('/var/www/'):
                raw_directory = os.path.join(base_dir, raw_directory.lstrip('/'))

            # Resolve the absolute path, removing any ../ or ./
            absolute_dir = os.path.abspath(raw_directory)

            # Ensure the final resolved path is still strictly within /var/www/
            if not absolute_dir.startswith(base_dir + '/'):
                flash("Invalid directory path. Must be within /var/www/", "danger")
                return redirect(url_for('ftp'))

            success, message = create_ftp_user(username, password, absolute_dir)
            flash(message, 'success' if success else 'danger')

        elif action == 'delete':
            username = request.form.get('username')
            success, message = delete_ftp_user(username)
            flash(message, 'success' if success else 'danger')

        elif action == 'password':
            username = request.form.get('username')
            new_password = request.form.get('new_password')
            success, message = change_ftp_password(username, new_password)
            flash(message, 'success' if success else 'danger')

        return redirect(url_for('ftp'))

    users = get_ftp_users() if ftp_installed else None
    return render_template('ftp.html', ftp_installed=ftp_installed, users=users)

from security_mgr import (check_csf_installed, get_csf_status, csf_action, csf_ip_action,
                           get_csf_file, save_csf_file, check_modsec_installed, get_modsec_status,
                           set_modsec_status, get_modsec_audit_log, get_csf_temp_entries,
                           get_open_ports, get_csf_conf_settings, save_csf_conf_key)

@app.route('/security', methods=['GET', 'POST'])
@login_required
def security():
    csf_installed = check_csf_installed()
    modsec_installed = check_modsec_installed()

    if request.method == 'POST':
        action = request.form.get('action')

        # CSF Actions
        if action in ['start', 'stop', 'restart']:
            success, message = csf_action(action)
            flash(message, 'success' if success else 'danger')

        elif action in ['allow_ip', 'deny_ip', 'unallow_ip', 'undeny_ip']:
            ip = request.form.get('ip')
            # remove _ip from action
            action_type = action.split('_')[0]
            success, message = csf_ip_action(action_type, ip)
            flash(message, 'success' if success else 'danger')

        elif action == 'save_csf_file':
            file_type = request.form.get('file_type')
            content = request.form.get('content')
            success, message = save_csf_file(file_type, content)
            flash(message, 'success' if success else 'danger')

        elif action == 'save_csf_conf_key':
            key   = request.form.get('conf_key')
            value = request.form.get('conf_value')
            success, message = save_csf_conf_key(key, value)
            flash(message, 'success' if success else 'danger')

        elif action == 'remove_temp':
            ip = request.form.get('ip')
            entry_type = request.form.get('entry_type', 'deny').lower()
            rm_action = 'unallow' if entry_type == 'allow' else 'undeny'
            success, message = csf_ip_action(rm_action, ip)
            flash(message, 'success' if success else 'danger')

        # ModSec Actions
        elif action == 'set_modsec_status':
            status = request.form.get('status')
            success, message = set_modsec_status(status)
            flash(message, 'success' if success else 'danger')

        return redirect(url_for('security'))

    # GET Request info
    context = {
        'csf_installed':    csf_installed,
        'csf_status':       get_csf_status() if csf_installed else None,
        'csf_allow_file':   get_csf_file('allow')  if csf_installed else "",
        'csf_deny_file':    get_csf_file('deny')   if csf_installed else "",
        'csf_ignore_file':  get_csf_file('ignore') if csf_installed else "",
        'csf_pignore_file': get_csf_file('pignore') if csf_installed else "",
        'csf_config_file':  get_csf_file('config') if csf_installed else "",
        'csf_temp':         get_csf_temp_entries() if csf_installed else [],
        'csf_ports':        get_open_ports()        if csf_installed else {},
        'csf_conf_settings': get_csf_conf_settings() if csf_installed else [],
        'modsec_installed': modsec_installed,
        'modsec_status':    get_modsec_status()     if modsec_installed else None,
        'modsec_log':       get_modsec_audit_log()  if modsec_installed else ""
    }

    return render_template('security.html', **context)

from settings_mgr import get_system_logs, get_editable_configs, read_config_file, save_config_file

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'save_config':
            filepath = request.form.get('filepath')
            content = request.form.get('content')
            success, message = save_config_file(filepath, content)
            flash(message, 'success' if success else 'danger')
            return redirect(url_for('settings'))

    logs = get_system_logs()
    configs = get_editable_configs()
    return render_template('settings.html', logs=logs, configs=configs)

@app.route('/settings/edit-config')
@login_required
def edit_config():
    filepath = request.args.get('filepath')
    if not filepath:
        flash("No file specified.", "danger")
        return redirect(url_for('settings'))

    success, content = read_config_file(filepath)
    if not success:
        flash(content, "danger")
        return redirect(url_for('settings'))

    return render_template('edit_config.html', filepath=filepath, content=content)

if __name__ == '__main__':
    # Run on all interfaces, port 2083
    app.run(host='0.0.0.0', port=2083, debug=True)
