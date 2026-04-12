from flask import Flask, render_template, request, redirect, url_for, session, flash
import os

# Ensure standard bin directories are available in the PATH for all subprocess calls
os.environ["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:" + os.environ.get("PATH", "")

import psutil
from auth import check_system_password, login_required
from dotenv import load_dotenv
from flask_wtf.csrf import CSRFProtect

load_dotenv()
from security_mgr import validate_input, is_safe_path, python_grep

app = Flask(__name__)
csrf = CSRFProtect(app)
# Persist secret key across restarts so sessions are not invalidated.
# Falls back to a random key if not in env, but logs a warning.
app.secret_key = os.environ.get('FLASK_SECRET_KEY')
if not app.secret_key:
    import logging
    logging.warning("No FLASK_SECRET_KEY set in environment. Using a random key. Sessions will invalidate on restart.")
    app.secret_key = os.urandom(24)

# --- Auto-Updater ---
import threading
import time
from updater_mgr import get_settings, get_version_info, perform_update, restart_service, save_settings

def auto_updater_worker():
    """Background thread to check for and apply updates."""
    # Wait for the app to fully start
    time.sleep(30)
    while True:
        try:
            settings = get_settings()
            if settings.get("auto_update"):
                info = get_version_info()
                if info.get("update_available"):
                    success, msg = perform_update()
                    if success:
                        restart_service()
        except Exception as e:
            print(f"Updater error: {e}")
        
        # Check every 1 hour
        time.sleep(3600)

# Start background thread
updater_thread = threading.Thread(target=auto_updater_worker, daemon=True)
updater_thread.start()
# --------------------


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

@app.route('/api/sysinfo')
@login_required
def api_sysinfo():
    import os
    import subprocess
    from flask import jsonify
    
    load1, load5, load15 = os.getloadavg()
    
    res = subprocess.run(['ps', 'aux', '--sort=-%cpu'], capture_output=True, text=True)
    lines = res.stdout.strip().split('\n')
    
    processes = []
    # Index 1 to 11 for the top 10 bypassing the header
    for line in lines[1:11]:
        parts = line.split(None, 10)
        if len(parts) == 11:
            cmd = parts[10]
            if len(cmd) > 50: cmd = cmd[:47] + '...'
            processes.append({
                'user': parts[0],
                'pid': parts[1],
                'cpu': parts[2],
                'mem': parts[3],
                'name': cmd
            })
            
    return jsonify({
        'load': [round(load1, 2), round(load5, 2), round(load15, 2)],
        'processes': processes
    })

@app.route('/api/services')
@login_required
def api_services():
    import subprocess
    from flask import jsonify
    from modsec_mgr import get_modsec_status
    
    res = subprocess.run("systemctl list-units --type=service --all | grep -m1 -oE 'php[0-9.]+-fpm\\.service'", shell=True, capture_output=True, text=True)
    php_fpm_id = res.stdout.strip().replace('.service', '') or 'php-fpm'

    services = [
        {'id': 'apache2', 'name': 'Apache Engine'},
        {'id': 'nginx', 'name': 'Nginx Engine'},
        {'id': php_fpm_id, 'name': 'PHP-FPM'}, 
        {'id': 'mariadb', 'name': 'MySQL / MariaDB'},
        {'id': 'csf', 'name': 'CSF Firewall'},
        {'id': 'cpanel', 'name': 'cPanel Platform'},
    ]

    for srv in services:
        sys_id = srv['id']
        chk = subprocess.run(['systemctl', 'is-active', sys_id], capture_output=True, text=True)
        status = chk.stdout.strip()
        srv['status'] = status if status in ['active', 'inactive', 'failed'] else 'not_installed'

    try:
        modsec_enabled = get_modsec_status() == 'On'
        apache_active = any(s['id'] == 'apache2' and s['status'] == 'active' for s in services)
        modsec_state = 'active' if (modsec_enabled and apache_active) else ('inactive' if modsec_enabled else 'not_installed')
    except Exception:
        modsec_state = 'unknown'

    services.append({
        'id': 'modsec',
        'name': 'ModSecurity',
        'status': modsec_state
    })

    return jsonify({'services': services})

@app.route('/api/services/restart', methods=['POST'])
@login_required
def api_service_restart():
    from flask import jsonify
    import subprocess
    
    service_id = request.json.get('service_id') if request.is_json else request.form.get('service_id')
    if not service_id:
        return jsonify({'success': False, 'message': 'Missing service identification.'})

    if service_id == 'modsec':
        res = subprocess.run(['systemctl', 'restart', 'apache2'], capture_output=True, text=True)
        if res.returncode == 0:
            return jsonify({'success': True, 'message': 'ModSecurity refreshed successfully.'})
        return jsonify({'success': False, 'message': f'Operation failed: {res.stderr}'})

    if service_id == 'cpanel':
        subprocess.Popen(['bash', '-c', 'sleep 1 && systemctl restart cpanel.service'])
        return jsonify({'success': True, 'message': 'Process initiated in background...'})

    if service_id not in ['apache2', 'nginx', 'mariadb', 'mysql', 'csf'] and not service_id.startswith('php'):
        return jsonify({'success': False, 'message': 'Forbidden infrastructure target.'})

    res = subprocess.run(['systemctl', 'restart', service_id], capture_output=True, text=True)
    if res.returncode == 0:
        return jsonify({'success': True, 'message': f'{service_id.title()} has been restarted successfully.'})
    else:
        return jsonify({'success': False, 'message': f'Crash/Timeout: {res.stderr}'})

from domains_mgr import get_virtual_hosts, add_virtual_host, toggle_virtual_host

@app.route('/domains', methods=['GET', 'POST'])
@login_required
def domains():
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'add':
            domain = request.form.get('domain')
            
            # SECURITY: Domain regex validation
            v, e = validate_input(domain, 'domain')
            if not v:
                flash(f"Validation failed: {e}", "danger")
                return redirect(url_for('domains'))

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

    path = available_logs.get(log_key)
    if not path:
         return jsonify({'error': 'Invalid log file.'}), 400

    # Standardize the path by removing our internal filter markers
    real_path = path.split(':', 1)[1] if ':' in path else path
    
    # SECURITY: Check if the path is in the provide allowlist
    if not is_safe_path(real_path):
        return jsonify({'error': 'Access denied: Path is not in the allowed log directory list.'}), 403

    try:
        # Use our secure Python-native grep replacement
        content = python_grep(real_path, domain, lines_int)
        
        if not content or not content.strip():
            content = '(Log is empty or has no matching entries yet.)'
            
        return jsonify({'content': content, 'path': real_path})
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
            
            # SECURITY: Explicit regex validation
            v1, e1 = validate_input(db_name, 'db_name')
            v2, e2 = validate_input(db_user, 'username')
            if not v1 or not v2:
                flash(f"Validation failed: {e1 or e2}", "danger")
                return redirect(url_for('databases'))

            success, message = create_database(db_name, db_user, db_pass)
            flash(message, 'success' if success else 'danger')

        elif action == 'delete':
            db_name = request.form.get('db_name')
            # SECURITY: Regex validation
            v, e = validate_input(db_name, 'db_name')
            if not v:
                flash(f"Validation failed: {e}", "danger")
                return redirect(url_for('databases'))
            success, message = delete_database(db_name)
            flash(message, 'success' if success else 'danger')

        elif action == 'change_password':
            db_user = request.form.get('db_user')
            host    = request.form.get('host')
            new_pw  = request.form.get('new_password')
            # SECURITY: Regex validation
            v, e = validate_input(db_user, 'username')
            if not v:
                flash(f"Validation failed: {e}", "danger")
                return redirect(url_for('databases'))
            success, message = change_user_password(db_user, host, new_pw)
            flash(message, 'success' if success else 'danger')

        elif action == 'update_host':
            db_name  = request.form.get('db_name')
            db_user  = request.form.get('db_user')
            old_host = request.form.get('old_host')
            new_host = request.form.get('new_host')
            # SECURITY: Regex validation
            v, e = validate_input(db_name, 'db_name')
            v2, e2 = validate_input(db_user, 'username')
            if not v or not v2:
                flash(f"Validation failed: {e or e2}", "danger")
                return redirect(url_for('databases'))
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

            # SECURITY: Username regex validation
            v, e = validate_input(username, 'username')
            if not v:
                flash(f"Validation failed: {e}", "danger")
                return redirect(url_for('ftp'))

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
            # SECURITY: Username regex validation
            v, e = validate_input(username, 'username')
            if not v:
                flash(f"Validation failed: {e}", "danger")
                return redirect(url_for('ftp'))
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

from csf_mgr import (check_csf_installed, get_csf_status, csf_action, csf_ip_action,
                           get_csf_file, save_csf_file, get_csf_temp_entries,
                           get_open_ports, get_csf_conf_settings, save_csf_conf_key)
from modsec_mgr import (check_modsec_installed, get_modsec_status, set_modsec_status,
                        get_modsec_profiles, get_domains_modsec_status, toggle_domain_modsec,
                        get_modsec_config, save_modsec_config, get_modsec_audit_log,
                        activate_modsec_profile, test_modsec_config, webserver_action)

@app.route('/firewall', methods=['GET', 'POST'])
@login_required
def firewall():
    csf_installed = check_csf_installed()

    if request.method == 'POST':
        action = request.form.get('action')

        if action in ['start', 'stop', 'restart']:
            success, message = csf_action(action)
            flash(message, 'success' if success else 'danger')

        elif action in ['allow_ip', 'deny_ip', 'unallow_ip', 'undeny_ip']:
            ip = request.form.get('ip')
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

        return redirect(url_for('firewall'))

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
    }
    return render_template('firewall.html', **context)


@app.route('/modsecurity', methods=['GET', 'POST'])
@login_required
def modsecurity():
    modsec_installed = check_modsec_installed()

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'install_modsec':
            from modsec_mgr import install_modsecurity_generator
            from flask import Response, stream_with_context
            return Response(stream_with_context(install_modsecurity_generator()), mimetype='application/x-ndjson')

        if action == 'set_modsec_status':
            status = request.form.get('status')
            success, message = set_modsec_status(status)
            flash(message, 'success' if success else 'danger')
        
        elif action == 'toggle_domain':
            domain = request.form.get('domain')
            enabled = request.form.get('enabled') == 'true'
            success, message = toggle_domain_modsec(domain, enabled)
            flash(message, 'success' if success else 'danger')
            
        elif action == 'save_config':
            file_type = request.form.get('file_type')
            content = request.form.get('content')
            success, message = save_modsec_config(file_type, content)
            flash(message, 'success' if success else 'danger')
        
        elif action == 'activate_profile':
            profile_id = request.form.get('profile_id')
            success, message = activate_modsec_profile(profile_id)
            flash(message, 'success' if success else 'danger')

        elif action == 'test_config':
            success, message = test_modsec_config()
            flash(message, 'success' if success else 'danger')

        elif action in ['reload', 'restart']:
            success, message = webserver_action(action)
            flash(message, 'success' if success else 'danger')

        return redirect(url_for('modsecurity'))

    domain_filter = request.args.get('domain')

    context = {
        'modsec_installed': modsec_installed,
        'modsec_status':    get_modsec_status()     if modsec_installed else None,
        'modsec_log':       get_modsec_audit_log(domain_filter) if modsec_installed else "",
        'modsec_profiles':  get_modsec_profiles()   if modsec_installed else [],
        'domain_modsec':    get_domains_modsec_status() if modsec_installed else [],
        'main_config':      get_modsec_config('main')   if modsec_installed else "",
        'custom_rules':     get_modsec_config('custom') if modsec_installed else "",
        'disabled_rules':   get_modsec_config('disabled') if modsec_installed else "",
        'current_filter':   domain_filter
    }
    return render_template('modsecurity.html', **context)

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

        elif action == 'update_settings':
            auto_up = request.form.get('auto_update') == 'on'
            s = get_settings()
            s['auto_update'] = auto_up
            save_settings(s)
            flash("Updater settings saved.", "success")

        elif action == 'check_update':
            info = get_version_info()
            if info.get('update_available'):
                flash(f"Update available: {info['remote']}. Click 'Update Now' to apply.", "info")
            else:
                flash("System is up to date.", "success")

        elif action == 'apply_update':
            success, msg = perform_update()
            if success:
                flash("Update applied! Restarting Lite cPanel...", "success")
                restart_service()
            else:
                flash(msg, "danger")

        return redirect(url_for('settings'))

    logs = get_system_logs()
    configs = get_editable_configs()
    
    # Version info
    ver_info = get_version_info()
    updater_settings = get_settings()

    return render_template('settings.html', 
                           logs=logs, 
                           configs=configs, 
                           ver_info=ver_info, 
                           updater_settings=updater_settings)

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
    return render_template('edit_config.html', filepath=filepath, content=content,
                           back_url=url_for('settings'), back_label='Back to Settings')

@app.route('/domains/edit-vhost')
@login_required
def edit_vhost():
    """Dedicated editor for Apache/Nginx vhost config files, accessed from the Domains page."""
    import subprocess
    filepath = request.args.get('filepath', '')
    if not filepath:
        flash("No file specified.", "danger")
        return redirect(url_for('domains'))

    # SECURITY: Only allow files inside the vhost directories — hard security boundary
    if not is_safe_path(filepath):
        flash("Access denied: that file is not in an allowed directory.", "danger")
        return redirect(url_for('domains'))

    import os
    if not os.path.exists(filepath):
        flash(f"File not found: {filepath}", "danger")
        return redirect(url_for('domains'))

    if request.method == 'POST' if False else False:
        pass  # see edit_vhost_save below

    try:
        with open(filepath, 'r') as f:
            content = f.read()
    except Exception as e:
        flash(str(e), "danger")
        return redirect(url_for('domains'))

    return render_template('edit_config.html', filepath=filepath, content=content,
                           back_url=url_for('domains'), back_label='Back to Domains',
                           save_url=url_for('save_vhost'))

@app.route('/domains/save-vhost', methods=['POST'])
@login_required
def save_vhost():
    """Save handler for vhost files edited from the Domains page."""
    import subprocess
    filepath = request.form.get('filepath', '')
    content  = request.form.get('content', '')

    # SECURITY: Only allow files inside the vhost directories — hard security boundary
    if not is_safe_path(filepath):
        flash("Access denied: cannot save to that directory.", "danger")
        return redirect(url_for('domains'))

    try:
        with open(filepath, 'w') as f:
            f.write(content)
        # Reload relevant server
        if 'apache2' in filepath:
            subprocess.run(['systemctl', 'reload', 'apache2'], capture_output=True)
        elif 'nginx' in filepath:
            subprocess.run(['systemctl', 'reload', 'nginx'], capture_output=True)
        flash("Virtual host config saved and service reloaded.", "success")
    except Exception as e:
        flash(str(e), "danger")

    return redirect(url_for('domains'))

from wordpress_mgr import get_installed_wordpress

@app.route('/wordpress', methods=['GET', 'POST'])
@login_required
def wordpress():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'install_wp':
            domain = request.form.get('domain')
            target_path = request.form.get('target_path', '').strip()
            
            # SECURITY: Strict input validation
            v, e = validate_input(domain, 'domain')
            if not v:
                 return Response(json.dumps({"progress": 100, "message": f"Validation failed: {e}", "error": True}) + "\n", mimetype='application/x-ndjson')

            from wordpress_mgr import install_wordpress_generator
            from flask import Response, stream_with_context
            return Response(stream_with_context(install_wordpress_generator(domain, target_path)), mimetype='application/x-ndjson')
        elif action == 'delete_wp':
            path = request.form.get('path')
            
            # SECURITY: Path boundary check
            if not is_safe_path(path):
                flash("Access denied: Invalid deletion path.", "danger")
                return redirect(url_for('wordpress'))

            from wordpress_mgr import delete_wordpress
            success, msg = delete_wordpress(path)
            flash(msg, 'success' if success else 'danger')
            return redirect(url_for('wordpress'))

    from domains_mgr import get_virtual_hosts
    domains = get_virtual_hosts()
    wp_installs = get_installed_wordpress(domains)
    return render_template('wordpress.html', domains=domains, wp_installs=wp_installs)

if __name__ == '__main__':
    # Run on all interfaces, port 2083
    app.run(host='0.0.0.0', port=2083, debug=True)
