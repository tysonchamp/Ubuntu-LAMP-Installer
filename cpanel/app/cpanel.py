from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import os
import threading
from flask_wtf.csrf import CSRFProtect
from flask_sock import Sock
from dotenv import load_dotenv

# --- Lite-cPanel Custom Imports ---
from config import init_environment, get_flask_secret_key
from auth import check_system_password, login_required, log_auth_failure
from security_mgr import validate_input, is_safe_path, python_grep, check_dns_resolution
from terminal_mgr import register_terminal_websocket
from updater_mgr import auto_updater_worker, get_version_info, get_settings, save_settings, perform_update, restart_service
from system_mgr import (start_background_workers, get_system_stats, get_server_info, 
                        get_process_list, DASHBOARD_CACHE)
from lib.utils import datetimeformat

# Initialize environment and load env variables
init_environment()
load_dotenv()

app = Flask(__name__)
csrf = CSRFProtect(app)
app.secret_key = get_flask_secret_key()
app.config['MAX_CONTENT_LENGTH'] = 1000 * 1024 * 1024  # 1GB limit

# Template filters
app.jinja_env.filters['datetimeformat'] = datetimeformat

sock = Sock(app)
register_terminal_websocket(sock)

# --- Start Background Workers ---
start_background_workers()
threading.Thread(target=auto_updater_worker, daemon=True).start()

# --------------------
# ROUTES
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
            # Auto-Whitelist IP in CSF (Temporary Allow for 1 Hour)
            try:
                user_ip = request.headers.get('CF-Connecting-IP') or \
                          request.headers.get('X-Real-IP') or \
                          request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
                
                import subprocess
                subprocess.run(['/usr/sbin/csf', '-ta', user_ip, '3600', f'cPanel Login: {username}'], capture_output=True, text=True)
            except Exception:
                pass

            session['logged_in'] = True
            session['username'] = username
            flash('Logged in successfully!', 'success')

            next_page = request.args.get('next')
            if not next_page or not next_page.startswith('/'):
                next_page = url_for('dashboard')
            return redirect(next_page)
        else:
            user_ip = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
            log_auth_failure(username, user_ip)
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
    stats = get_system_stats()
    stats['user_ip'] = request.headers.get('CF-Connecting-IP') or \
                       request.headers.get('X-Real-IP') or \
                       request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip() or "Unknown"
    
    server_info = get_server_info()
    traffic_stats = DASHBOARD_CACHE.get('traffic', [])
    
    return render_template('dashboard.html', server_info=server_info, stats=stats, traffic_stats=traffic_stats)

@app.route('/api/sysinfo')
@login_required
def api_sysinfo():
    stats = get_system_stats()
    processes = get_process_list()
    return jsonify({
        'cpu_percent': stats['cpu'],
        'ram_total': stats['ram_total'],
        'ram_used': stats['ram_used'],
        'ram_percent': stats['ram_percent'],
        'disk_total': stats['disk_total'],
        'disk_used': stats['disk_used'],
        'disk_percent': stats['disk_percent'],
        'processes': processes
    })

@app.route('/traffic')
@login_required
def traffic_monitor():
    from system_mgr import get_dashboard_traffic
    traffic_stats = get_dashboard_traffic()
    return render_template('traffic.html', traffic_stats=traffic_stats)

@app.route('/traffic/report/<domain>')
@login_required
def traffic_report(domain):
    from system_mgr import subprocess
    nginx_log = f"/var/log/nginx/{domain}_access.log"
    apache_log = f"/var/log/apache2/{domain}_access.log"
    log_file = nginx_log if os.path.exists(nginx_log) else (apache_log if os.path.exists(apache_log) else None)
    
    if not log_file:
        return "Log file not found for this domain.", 404
        
    try:
        goaccess_path = '/usr/bin/goaccess'
        if not os.path.exists(goaccess_path): goaccess_path = 'goaccess'
        
        cmd = [goaccess_path, log_file, '--log-format=COMBINED', '--no-global-config', '-o', 'html']
        res = subprocess.run(cmd, capture_output=True)
        
        if res.returncode != 0:
            cmd = [goaccess_path, log_file, '--log-format=VCOMMON', '--no-global-config', '-o', 'html']
            res = subprocess.run(cmd, capture_output=True)
            
        if res.returncode == 0:
            from flask import make_response
            response = make_response(res.stdout)
            response.headers['Content-Type'] = 'text/html'
            return response
        else:
            return f"GoAccess Error: {res.stderr.decode('utf-8', errors='ignore')}", 500
    except Exception as e:
        return f"System Error: {str(e)}", 500

@app.route('/api/services')
@login_required
def api_services():
    from system_mgr import get_services_status
    services = get_services_status()
    return jsonify({'services': services})

@app.route('/api/services/restart', methods=['POST'])
@login_required
def api_service_restart():
    from system_mgr import restart_system_service
    service_id = request.json.get('service_id') if request.is_json else request.form.get('service_id')
    if not service_id:
        return jsonify({'success': False, 'message': 'Missing service identification.'})

    success, message = restart_system_service(service_id)
    return jsonify({'success': success, 'message': message})

from domains_mgr import get_virtual_hosts, add_virtual_host, toggle_virtual_host, get_port80_webserver

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
                # Automatically choose plugin based on which webserver is on port 80
                detected = get_port80_webserver(domain)
                if detected == 'nginx':
                    plugin = '--nginx'
                elif detected == 'apache':
                    plugin = '--apache'
                else:
                    # Fallback to existing heuristic if config inspection fails
                    plugin = '--nginx' if 'Nginx' in servers and 'Apache' not in servers else '--apache'
                
                logging.info(f"Generating SSL for {domain} using {plugin} (detected: {detected})")
                
                # Build domain list - only include www if it actually resolves
                domain_args = ['-d', domain]
                if check_dns_resolution(f"www.{domain}"):
                    domain_args.extend(['-d', f'www.{domain}'])
                else:
                    logging.info(f"Skipping www.{domain} as it does not resolve in DNS.")

                cmd = ['certbot', plugin] + domain_args + ['--non-interactive', '--agree-tos', '-m', f'admin@{domain}']
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

from nextjs_mgr import get_nextjs_apps, add_nextjs_app, toggle_nextjs_app, delete_nextjs_app

@app.route('/nextjs', methods=['GET', 'POST'])
@login_required
def nextjs():
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'add':
            domain = request.form.get('domain')
            port = request.form.get('port')
            
            # SECURITY: Domain regex validation
            v, e = validate_input(domain, 'domain')
            if not v:
                flash(f"Validation failed: {e}", "danger")
                return redirect(url_for('nextjs'))

            if not port or not port.isdigit():
                flash("Invalid port number.", "danger")
                return redirect(url_for('nextjs'))

            success, message = add_nextjs_app(domain, port)
            if success:
                flash(message, 'success')
            else:
                flash(message, 'danger')

        elif action == 'toggle':
            domain = request.form.get('domain')
            enable_str = request.form.get('enable')
            enable = enable_str.lower() == 'true'

            success, message = toggle_nextjs_app(domain, enable)
            if success:
                flash(message, 'success')
            else:
                flash(message, 'danger')

        elif action == 'delete':
            domain = request.form.get('domain')
            success, message = delete_nextjs_app(domain)
            if success:
                flash(message, 'success')
            else:
                flash(message, 'danger')

        elif action == 'ssl_generate':
            domain = request.form.get('domain')
            servers = request.form.get('servers', '')
            import subprocess
            try:
                # Automatically choose plugin based on which webserver is on port 80
                detected = get_port80_webserver(domain)
                if detected == 'nginx':
                    plugin = '--nginx'
                elif detected == 'apache':
                    plugin = '--apache'
                else:
                    plugin = '--nginx' if 'Nginx' in servers and 'Apache' not in servers else '--apache'
                
                logging.info(f"Generating SSL (Next.js) for {domain} using {plugin} (detected: {detected})")
                
                # Build domain list - only include www if it actually resolves
                domain_args = ['-d', domain]
                if check_dns_resolution(f"www.{domain}"):
                    domain_args.extend(['-d', f'www.{domain}'])
                
                cmd = ['certbot', plugin] + domain_args + ['--non-interactive', '--agree-tos', '-m', f'admin@{domain}']
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

        return redirect(url_for('nextjs'))

    nextjs_apps = get_nextjs_apps()
    return render_template('nextjs.html', nextjs_apps=nextjs_apps)

@app.route('/terminal')
@login_required
def terminal():
    return render_template('terminal.html')

from cron_mgr import get_cron_jobs, add_cron_job, delete_cron_job, enable_ssl_renewal

@app.route('/cron', methods=['GET', 'POST'])
@login_required
def cron():
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add':
            schedule = request.form.get('schedule', '')
            command = request.form.get('command', '')
            success, msg = add_cron_job(schedule, command)
            flash(msg, "success" if success else "danger")
            
        elif action == 'delete':
            index = request.form.get('index')
            success, msg = delete_cron_job(index)
            flash(msg, "success" if success else "danger")
            
        elif action == 'setup_ssl':
            success, msg = enable_ssl_renewal()
            flash(msg, "success" if success else "warning")
            
        return redirect(url_for('cron'))

    cron_jobs = get_cron_jobs()
    return render_template('cron.html', cron_jobs=cron_jobs)

from backup_mgr import get_backup_settings, save_backup_settings, trigger_manual_backup, get_local_backups, delete_local_backup

@app.route('/backups', methods=['GET', 'POST'])
@login_required
def backups():
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'save_settings':
            settings = {
                'local_enabled': request.form.get('local_enabled') == 'yes',
                'ftp_enabled': request.form.get('ftp_enabled') == 'yes',
                'ftp_host': request.form.get('ftp_host', ''),
                'ftp_port': request.form.get('ftp_port', '21'),
                'ftp_user': request.form.get('ftp_user', ''),
                'ftp_pass': request.form.get('ftp_pass', ''),
                'ftp_path': request.form.get('ftp_path', '/'),
                's3_enabled': request.form.get('s3_enabled') == 'yes',
                's3_endpoint': request.form.get('s3_endpoint', ''),
                's3_access_key': request.form.get('s3_access_key', ''),
                's3_secret_key': request.form.get('s3_secret_key', ''),
                's3_bucket': request.form.get('s3_bucket', ''),
                's3_region': request.form.get('s3_region', ''),
                'retention_days': int(request.form.get('retention_days', 7)),
                'schedule': request.form.get('schedule', '').strip()
            }
            success, msg = save_backup_settings(settings)
            flash(msg, "success" if success else "danger")
            
        elif action == 'trigger_backup':
            success, msg = trigger_manual_backup()
            flash(msg, "success" if success else "danger")
            
        elif action == 'delete_backup':
            filename = request.form.get('filename')
            success, msg = delete_local_backup(filename)
            flash(msg, "success" if success else "danger")
            
        return redirect(url_for('backups'))

    settings = get_backup_settings()
    local_backups = get_local_backups()
    return render_template('backups.html', settings=settings, local_backups=local_backups)

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

from mongodb_mgr import (check_mongodb_installed, install_mongodb, get_databases as get_mongo_dbs,
                         create_database as create_mongo_db, delete_database as delete_mongo_db,
                         change_user_password as change_mongo_pass,
                         check_mongo_express_installed, install_mongo_express,
                         get_mongo_express_status, restart_mongo_express,
                         get_mongo_express_credentials)

@app.route('/mongodb', methods=['GET', 'POST'])
@login_required
def mongodb_route():
    is_installed = check_mongodb_installed()
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'install':
            success, msg = install_mongodb()
            flash(msg, 'success' if success else 'danger')
            return redirect(url_for('mongodb_route'))
        
        if action == 'install_express':
            success, msg = install_mongo_express()
            flash(msg, 'success' if success else 'danger')
            return redirect(url_for('mongodb_route'))
        
        if action == 'restart_express':
            success, msg = restart_mongo_express()
            flash(msg, 'success' if success else 'danger')
            return redirect(url_for('mongodb_route'))
            
        if not is_installed:
            flash("MongoDB is not installed.", "danger")
            return redirect(url_for('mongodb_route'))
            
        if action == 'create':
            db_name = request.form.get('db_name')
            db_user = request.form.get('db_user')
            db_pass = request.form.get('db_pass')
            
            # Use same validation as mysql
            v1, e1 = validate_input(db_name, 'db_name')
            v2, e2 = validate_input(db_user, 'username')
            if not v1 or not v2:
                flash(f"Validation failed: {e1 or e2}", "danger")
                return redirect(url_for('mongodb_route'))
                
            success, message = create_mongo_db(db_name, db_user, db_pass)
            flash(message, 'success' if success else 'danger')
            
        elif action == 'delete':
            db_name = request.form.get('db_name')
            v, e = validate_input(db_name, 'db_name')
            if not v:
                flash(f"Validation failed: {e}", "danger")
                return redirect(url_for('mongodb_route'))
            success, message = delete_mongo_db(db_name)
            flash(message, 'success' if success else 'danger')
            
        elif action == 'change_password':
            db_name = request.form.get('db_name')
            db_user = request.form.get('db_user')
            new_pass = request.form.get('new_password')
            
            v1, e1 = validate_input(db_name, 'db_name')
            v2, e2 = validate_input(db_user, 'username')
            if not v1 or not v2:
                flash(f"Validation failed: {e1 or e2}", "danger")
                return redirect(url_for('mongodb_route'))
                
            success, message = change_mongo_pass(db_name, db_user, new_pass)
            flash(message, 'success' if success else 'danger')
            
        return redirect(url_for('mongodb_route'))
        
    db_details = get_mongo_dbs() if is_installed else []
    me_status = get_mongo_express_status() if is_installed else 'not_installed'
    me_creds = get_mongo_express_credentials() if me_status == 'active' else {}
    return render_template('mongodb.html', is_installed=is_installed, db_details=db_details,
                           me_status=me_status, me_creds=me_creds)

@app.route('/phpmyadmin-login')
@login_required
def phpmyadmin_login():
    """Simple redirect to phpMyAdmin without auto-login."""
    host = request.host.split(':')[0]
    return redirect(f"http://{host}/phpmyadmin/")


from nextjs_mgr import get_nextjs_apps
from process_mgr import (is_pm2_installed, list_processes, 
                         manage_process, start_nextjs_app, get_process_logs, run_npm_command)

@app.route('/processes', methods=['GET', 'POST'])
@login_required
def process_manager():
    pm2_ready = is_pm2_installed()
    configured_apps = get_nextjs_apps()
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add_app':
            name = request.form.get('name')
            path = request.form.get('path')
            port = request.form.get('port') or None
            success, msg = start_nextjs_app(path, name, port)
            flash(msg, 'success' if success else 'danger')
            
        elif action in ['stop', 'restart', 'delete', 'start']:
            name = request.form.get('name')
            success, msg = manage_process(action, name)
            flash(msg, 'success' if success else 'danger')
            
        elif action == 'npm_install':
            path = request.form.get('path')
            success, msg = run_npm_command(path, 'install')
            flash(msg, 'success' if success else 'danger')

        elif action == 'npm_build':
            path = request.form.get('path')
            success, msg = run_npm_command(path, 'run build')
            flash(msg, 'success' if success else 'danger')

        return redirect(url_for('process_manager'))

    processes = list_processes()
    return render_template('processes.html', pm2_ready=pm2_ready, processes=processes, configured_apps=configured_apps)

@app.route('/api/processes/logs/<name>')
@login_required
def api_process_logs(name):
    from flask import jsonify
    logs = get_process_logs(name)
    return jsonify({'logs': logs})

from ftp_mgr import (check_pureftpd_installed, create_ftp_user, delete_ftp_user, 
                     change_ftp_password, get_ftp_users)

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

        elif action == 'toggle_sftp':
            from ftp_mgr import toggle_sftp
            enable = request.form.get('enable') == 'true'
            success, message = toggle_sftp(enable)
            flash(message, 'success' if success else 'danger')

        elif action == 'toggle_user_status':
            from ftp_mgr import toggle_ftp_user_status
            username = request.form.get('username')
            enable = request.form.get('enable') == 'true'
            success, message = toggle_ftp_user_status(username, enable)
            flash(message, 'success' if success else 'danger')

        return redirect(url_for('ftp'))

    from ftp_mgr import get_sftp_status
    sftp_enabled = get_sftp_status()
    users = get_ftp_users() if ftp_installed else None
    return render_template('ftp.html', ftp_installed=ftp_installed, users=users, sftp_enabled=sftp_enabled)

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

        elif action == 'remove_rule':
            file_type = request.form.get('file_type')
            rule_raw = request.form.get('rule_raw')
            from csf_mgr import remove_from_csf_file
            success, message = remove_from_csf_file(file_type, rule_raw)
            flash(message, 'success' if success else 'danger')

        return redirect(url_for('firewall'))

    from csf_mgr import get_parsed_csf_file
    context = {
        'csf_installed':    csf_installed,
        'csf_status':       get_csf_status() if csf_installed else None,
        'csf_allow_file':   get_csf_file('allow')  if csf_installed else "",
        'csf_deny_file':    get_csf_file('deny')   if csf_installed else "",
        'csf_ignore_file':  get_csf_file('ignore') if csf_installed else "",
        'csf_pignore_file': get_csf_file('pignore') if csf_installed else "",
        'csf_regex_file':   get_csf_file('regex') if csf_installed else "",
        'csf_config_file':  get_csf_file('config') if csf_installed else "",
        'parsed_allow':     get_parsed_csf_file('allow') if csf_installed else [],
        'parsed_deny':      get_parsed_csf_file('deny') if csf_installed else [],
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
    from settings_mgr import handle_settings_action
    if request.method == 'POST':
        success, message = handle_settings_action(request)
        flash(message, 'success' if success else 'danger')
        return redirect(url_for('settings'))

    logs = get_system_logs()
    configs = get_editable_configs()
    
    import socket    
    # Version info
    ver_info = get_version_info()
    updater_settings = get_settings()
    current_hostname = socket.gethostname()

    return render_template('settings.html', 
                           logs=logs, 
                           configs=configs, 
                           ver_info=ver_info, 
                           updater_settings=updater_settings,
                           current_hostname=current_hostname)

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

    source = request.args.get('source', 'domains')
    back_url = url_for('nextjs') if source == 'nextjs' else url_for('domains')
    back_label = 'Back to Next.js Apps' if source == 'nextjs' else 'Back to Domains'

    # SECURITY: Only allow files inside the vhost directories — hard security boundary
    if not is_safe_path(filepath):
        flash("Access denied: that file is not in an allowed directory.", "danger")
        return redirect(back_url)

    import os
    if not os.path.exists(filepath):
        flash(f"File not found: {filepath}", "danger")
        return redirect(back_url)

    if request.method == 'POST' if False else False:
        pass  # see edit_vhost_save below

    try:
        with open(filepath, 'r') as f:
            content = f.read()
    except Exception as e:
        flash(str(e), "danger")
        return redirect(back_url)

    return render_template('edit_config.html', filepath=filepath, content=content,
                           back_url=back_url, back_label=back_label,
                           save_url=url_for('save_vhost', source=source))

@app.route('/domains/save-vhost', methods=['POST'])
@login_required
def save_vhost():
    """Save handler for vhost files edited from the Domains page."""
    import subprocess
    filepath = request.form.get('filepath', '')
    content  = request.form.get('content', '')

    source = request.args.get('source', 'domains')
    back_url = url_for('nextjs') if source == 'nextjs' else url_for('domains')

    # SECURITY: Only allow files inside the vhost directories — hard security boundary
    if not is_safe_path(filepath):
        flash("Access denied: cannot save to that directory.", "danger")
        return redirect(back_url)

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

    return redirect(back_url)

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

# --- File Manager ---
import datetime as _dt

@app.template_filter('datetimeformat')
def _datetimeformat(ts):
    try:
        return _dt.datetime.fromtimestamp(int(ts)).strftime('%Y-%m-%d %H:%M')
    except Exception:
        return ''

from filemanager_mgr import list_dir, read_file, write_file, create_folder, rename_entry, delete_entry, save_upload, compress_entries, decompress_entry, is_archive

@app.route('/filemanager', methods=['GET', 'POST'], strict_slashes=False)
@login_required
def filemanager_route():
    path = request.args.get('path', '/var/www/html')

    if request.method == 'POST':
        action = request.form.get('action')
        redirect_path = request.form.get('redirect_path', path)

        if action == 'mkdir':
            ok, msg = create_folder(request.form.get('path', path), request.form.get('name', ''))
            flash(msg, 'success' if ok else 'danger')
            return redirect(url_for('filemanager_route') + f'?path={quote(request.form.get("path", path))}')

        elif action == 'upload':
            upload_path = request.form.get('path', path)
            files = request.files.getlist('file')
            for f in files:
                ok, msg = save_upload(upload_path, f)
                flash(msg, 'success' if ok else 'danger')
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                from flask import jsonify
                return jsonify({'success': True, 'redirect': url_for('filemanager_route') + f'?path={quote(upload_path)}'})
                
            return redirect(url_for('filemanager_route') + f'?path={quote(upload_path)}')

        elif action == 'compress':
            names = request.form.getlist('names')
            archive_name = request.form.get('archive_name', 'archive')
            fmt = request.form.get('fmt', 'zip')
            ok, msg = compress_entries(path, names, archive_name, fmt)
            flash(msg, 'success' if ok else 'danger')
            return redirect(url_for('filemanager_route') + f'?path={quote(path)}')

        elif action == 'extract':
            ok, msg = decompress_entry(request.form.get('path', ''), os.path.dirname(request.form.get('path', '')))
            flash(msg, 'success' if ok else 'danger')
            return redirect(url_for('filemanager_route') + f'?path={quote(redirect_path)}')

        elif action == 'rename':
            ok, msg = rename_entry(request.form.get('path', ''), request.form.get('new_name', ''))
            flash(msg, 'success' if ok else 'danger')
            return redirect(url_for('filemanager_route') + f'?path={quote(redirect_path)}')

        elif action == 'delete':
            ok, msg = delete_entry(request.form.get('path', ''))
            flash(msg, 'success' if ok else 'danger')
            return redirect(url_for('filemanager_route') + f'?path={quote(redirect_path)}')

        elif action == 'save':
            ok, msg = write_file(request.form.get('path', ''), request.form.get('content', ''))
            flash(msg, 'success' if ok else 'danger')
            return redirect(url_for('filemanager_route') + f'?path={quote(redirect_path)}')

    data, err = list_dir(path)
    if err:
        flash(err, 'danger')
        data = {'path': '/var/www/html', 'entries': [], 'parent': '/'}

    for e in data['entries']:
        e['is_archive'] = not e['is_dir'] and is_archive(e['name'])

    return render_template('filemanager.html',
                           current_path=data['path'],
                           parent_path=data['parent'],
                           entries=data['entries'])

@app.route('/filemanager/read')
@login_required
def filemanager_read():
    from flask import jsonify
    path = request.args.get('path', '')
    content, err = read_file(path)
    if err:
        return jsonify({'error': err})
    return jsonify({'content': content})

@app.route('/filemanager/download')
@login_required
def filemanager_download():
    from flask import send_file
    import os
    from filemanager_mgr import _safe_path
    path = request.args.get('path', '')
    safe = _safe_path(path)
    if not safe or not os.path.isfile(safe):
        flash('File not found.', 'danger')
        return redirect(url_for('filemanager_route'))
    return send_file(safe, as_attachment=True)

if __name__ == '__main__':
    # Run on all interfaces, port 2083
    app.run(host='0.0.0.0', port=2083, debug=True)
