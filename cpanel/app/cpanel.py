from flask import Flask, render_template, request, redirect, url_for, session, flash
import os
import glob
from urllib.parse import quote

import glob

# Ensure consistent environment for PM2 and other system tools
if os.getuid() == 0:
    os.environ["HOME"] = "/root"
    os.environ["PM2_HOME"] = "/root/.pm2"

# Explicitly prioritize the user's working Node/PM2 path
# Fallback to general detection if version changes
paths = [
    "/root/.nvm/versions/node/v24.15.0/bin",
    "/usr/local/sbin", "/usr/local/bin", "/usr/sbin", "/usr/bin", "/sbin", "/bin"
]

import glob
nvm_node_paths = glob.glob(os.path.expanduser("~/.nvm/versions/node/*/bin"))
if nvm_node_paths:
    nvm_node_paths.sort(reverse=True)
    for p in nvm_node_paths:
        if p not in paths:
            paths.append(p)

os.environ["PATH"] = ":".join(paths) + ":" + os.environ.get("PATH", "")

# Auto-Resurrect PM2 processes on startup to ensure persistence
try:
    from process_mgr import get_pm2_cmd, PM2_HOME
    env = os.environ.copy()
    env["PM2_HOME"] = PM2_HOME
    subprocess.run([get_pm2_cmd(), 'resurrect'], capture_output=True, text=True, env=env)
except Exception:
    pass

import psutil

import psutil
import subprocess
from auth import check_system_password, login_required
from dotenv import load_dotenv
from flask_wtf.csrf import CSRFProtect

load_dotenv()
from security_mgr import validate_input, is_safe_path, python_grep, check_dns_resolution
import logging
from logging.handlers import RotatingFileHandler

# --- Auth Logging Setup for CSF/LFD ---
auth_logger = logging.getLogger('cpanel_auth')
auth_logger.setLevel(logging.INFO)
try:
    log_handler = RotatingFileHandler('/var/log/cpanel_auth.log', maxBytes=1000000, backupCount=5)
    log_handler.setFormatter(logging.Formatter('%(asctime)s %(message)s', '%b %d %H:%M:%S'))
    auth_logger.addHandler(log_handler)
except Exception:
    # Fallback if log dir isn't writable yet during init
    pass

def log_auth_failure(username, ip):
    auth_logger.info(f"Failed login attempt for user {username} from {ip}")

app = Flask(__name__)
csrf = CSRFProtect(app)
# Persist secret key across restarts so sessions are not invalidated.
# Falls back to a random key if not in env, but logs a warning.
app.secret_key = os.environ.get('FLASK_SECRET_KEY')
if not app.secret_key:
    import logging
    logging.warning("No FLASK_SECRET_KEY set in environment. Using a random key. Sessions will invalidate on restart.")
    app.secret_key = os.urandom(24)

from flask_sock import Sock
sock = Sock(app)
app.config['MAX_CONTENT_LENGTH'] = 1000 * 1024 * 1024  # 1GB limit

from terminal_mgr import register_terminal_websocket
register_terminal_websocket(sock)

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
            # Capture real IP even if behind proxy
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

    import platform
    import socket
    
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
    
    hostname = platform.node()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip_address = s.getsockname()[0]
        s.close()
    except Exception:
        ip_address = "Unknown"
        
    # Detailed CPU info
    try:
        with open('/proc/cpuinfo', 'r') as f:
            for line in f:
                if 'model name' in line:
                    processor = line.split(':')[1].strip()
                    break
            else:
                processor = platform.processor()
    except Exception:
        processor = platform.processor()

    # OS Info helper
    def get_os_name():
        try:
            with open("/etc/os-release") as f:
                d = {}
                for line in f:
                    if "=" in line:
                        k, v = line.rstrip().split("=", 1)
                        d[k] = v.strip('"')
                return d.get("PRETTY_NAME", "Linux")
        except:
            return platform.system()

    import datetime
    import sys
    
    boot_time = datetime.datetime.fromtimestamp(psutil.boot_time())
    uptime_delta = datetime.datetime.now() - boot_time
    # Simple formatting: X days, HH:MM
    days = uptime_delta.days
    hours, remainder = divmod(uptime_delta.seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    uptime_str = f"{days}d {hours}h {minutes}m"

    import urllib.request
    try:
        public_ip = urllib.request.urlopen('https://ident.me', timeout=3).read().decode('utf-8')
    except:
        public_ip = "Unknown"

    # Listening ports
    ports = []
    try:
        for conn in psutil.net_connections(kind='inet'):
            if conn.status == 'LISTEN':
                ports.append(conn.laddr.port)
        ports = sorted(list(set(ports)))
    except:
        ports = []

    # Recent SSH Logins (Last 5)
    ssh_logins = []
    
    def parse_ssh_line(line):
        import re
        from datetime import datetime
        
        # Try ISO format (2026-04-21T14:17:03...)
        iso_match = re.match(r'^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})', line)
        if iso_match:
            try:
                dt = datetime.strptime(iso_match.group(1), '%Y-%m-%dT%H:%M:%S')
                time_str = dt.strftime('%b %d %H:%M:%S')
            except:
                time_str = iso_match.group(1)
        else:
            # Fallback to Syslog format (Apr 21 14:17:03)
            parts = line.split()
            time_str = " ".join(parts[:3])

        # Extract message after 'sshd[PID]: '
        m = re.search(r'sshd\[\d+\]: (.*)', line)
        msg = m.group(1) if m else line
        return {'time': time_str, 'msg': msg}

    auth_log = '/var/log/auth.log'
    if not os.path.exists(auth_log): auth_log = '/var/log/secure'
    
    if os.path.exists(auth_log):
        try:
            res = subprocess.run(['tail', '-n', '200', auth_log], capture_output=True, text=True)
            for line in reversed(res.stdout.strip().split('\n')):
                if 'sshd' in line and any(x in line for x in ['Accepted', 'Failed', 'Invalid']):
                    ssh_logins.append(parse_ssh_line(line))
                    if len(ssh_logins) >= 5: break
        except: pass

    # Fallback to journalctl if log files are empty/inaccessible (common on newer Ubuntu versions)
    if not ssh_logins:
        try:
            res = subprocess.run(['journalctl', '_COMM=sshd', '-n', '100', '--no-pager'], capture_output=True, text=True)
            for line in reversed(res.stdout.strip().split('\n')):
                if any(x in line for x in ['Accepted', 'Failed', 'Invalid']):
                    ssh_logins.append(parse_ssh_line(line))
                    if len(ssh_logins) >= 5: break
        except: pass

    # Last Backup
    last_backup = "Never"
    backup_flag = '/var/lib/lite-cpanel/.last_backup'
    if os.path.exists(backup_flag):
        try:
            with open(backup_flag, 'r') as f:
                last_backup = f.read().strip()
        except:
            pass

    # Web Traffic Stats
    traffic_stats = []
    
    def get_domain_traffic(domain, log_file):
        if not os.path.exists(log_file): return None
        try:
            # Use absolute path to ensure binary is found on all systems
            goaccess_path = '/usr/bin/goaccess'
            if not os.path.exists(goaccess_path):
                goaccess_path = 'goaccess' # Fallback to PATH

            # Run goaccess in JSON mode
            cmd = [goaccess_path, log_file, '--log-format=COMBINED', '--no-global-config', '-o', 'json']
            res = subprocess.run(cmd, capture_output=True, text=True)
            
            if res.returncode != 0:
                logging.error(f"GoAccess failed for {domain} ({log_file}): {res.stderr}")
                return None
                
            data = json.loads(res.stdout)
            general = data.get('general', {})
            return {
                'domain': domain,
                'hits': general.get('total_requests', 0),
                'bandwidth': general.get('bandwidth', 0), # In bytes
                'visitors': general.get('unique_visitors', 0)
            }
        except Exception as e:
            logging.error(f"Error parsing traffic for {domain}: {str(e)}")
            return None

    from nextjs_mgr import get_nextjs_apps
    from domains_mgr import get_virtual_hosts
    
    # Collect all domains from both Next.js apps and standard virtual hosts
    all_domains = set()
    for app in get_nextjs_apps():
        all_domains.add(app['domain'])
    for host in get_virtual_hosts():
        all_domains.add(host['domain'])

    for domain in all_domains:
        # Check standard Nginx/Apache log patterns
        log_candidates = [
            f"/var/log/nginx/{domain}_access.log",
            f"/var/log/apache2/{domain}_access.log",
            f"/var/log/nginx/{domain}.access.log",
            f"/var/log/apache2/{domain}.access.log"
        ]
        
        stats = None
        for log_file in log_candidates:
            if os.path.exists(log_file):
                stats = get_domain_traffic(domain, log_file)
                if stats: break
        
        if stats:
            traffic_stats.append(stats)

    # Sort by bandwidth descending
    traffic_stats = sorted(traffic_stats, key=lambda x: x['bandwidth'], reverse=True)

    server_info = {
        'hostname': hostname,
        'ip_address': ip_address,
        'public_ip': public_ip,
        'processor': processor,
        'cpu_cores': psutil.cpu_count(logical=True),
        'cpu_physical': psutil.cpu_count(logical=False),
        'cpu_freq': f"{psutil.cpu_freq().current:.0f} MHz" if psutil.cpu_freq() else "N/A",
        'os': get_os_name(),
        'kernel': platform.release(),
        'platform': f"{platform.machine()} {platform.system()} ({platform.processor()})",
        'uptime': uptime_str,
        'python_version': sys.version.split()[0],
        'server_time': datetime.datetime.now().strftime("%a %b %d %H:%M:%S %Z %Y"),
        'listening_ports': ports,
        'ssh_logins': ssh_logins,
        'last_backup': last_backup
    }

    return render_template('dashboard.html', server_info=server_info, stats=stats, traffic_stats=traffic_stats)

@app.route('/traffic')
@login_required
def traffic_monitor():
    traffic_stats = []
    from nextjs_mgr import get_nextjs_apps
    all_apps = get_nextjs_apps()
    for app in all_apps:
        domain = app['domain']
        nginx_log = f"/var/log/nginx/{domain}_access.log"
        apache_log = f"/var/log/apache2/{domain}_access.log"
        
        # Helper logic already exists in dashboard route, I'll extract it or reuse
        # For now, I'll redefine it to keep it simple and isolated
        def get_domain_traffic(domain, log_file):
            if not os.path.exists(log_file): return None
            try:
                cmd = ['goaccess', log_file, '--log-format=COMBINED', '--no-global-config', '-o', 'json']
                res = subprocess.run(cmd, capture_output=True, text=True)
                if res.returncode == 0:
                    data = json.loads(res.stdout)
                    general = data.get('general', {})
                    return {
                        'domain': domain,
                        'hits': general.get('total_requests', 0),
                        'bandwidth': general.get('bandwidth', 0),
                        'visitors': general.get('unique_visitors', 0)
                    }
            except: pass
            return None
            
        stats = get_domain_traffic(domain, nginx_log) or get_domain_traffic(domain, apache_log)
        if stats:
            traffic_stats.append(stats)
            
    return render_template('traffic.html', traffic_stats=traffic_stats)

@app.route('/traffic/report/<domain>')
@login_required
def traffic_report(domain):
    nginx_log = f"/var/log/nginx/{domain}_access.log"
    apache_log = f"/var/log/apache2/{domain}_access.log"
    log_file = nginx_log if os.path.exists(nginx_log) else (apache_log if os.path.exists(apache_log) else None)
    
    if not log_file:
        return "Log file not found for this domain.", 404
        
    try:
        # Generate full HTML report from GoAccess
        cmd = ['goaccess', log_file, '--log-format=COMBINED', '--no-global-config', '-o', 'html']
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            return res.stdout # Return raw HTML report
    except Exception as e:
        return f"Error generating report: {str(e)}", 500
        
    return "Failed to generate report.", 500

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
            
    # Global stats
    cpu_percent = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')

    return jsonify({
        'cpu_percent': cpu_percent,
        'ram': {
            'used': round(mem.used / (1024**3), 2),
            'total': round(mem.total / (1024**3), 2),
            'percent': mem.percent
        },
        'disk': {
            'used': round(disk.used / (1024**3), 2),
            'total': round(disk.total / (1024**3), 2),
            'percent': disk.percent
        },
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
        {'id': 'mongod', 'name': 'MongoDB'},
        {'id': 'mongo-express', 'name': 'Mongo Express'},
        {'id': 'csf', 'name': 'CSF Firewall'},
        {'id': 'cpanel', 'name': 'cPanel Platform'},
    ]

    from mongodb_mgr import get_mongo_express_status
    for srv in services:
        sys_id = srv['id']
        if sys_id == 'mongo-express':
            me = get_mongo_express_status()
            srv['status'] = 'active' if me == 'active' else ('not_installed' if me == 'not_installed' else 'inactive')
            continue
        chk = subprocess.run(['systemctl', 'is-active', sys_id], capture_output=True, text=True)
        status = chk.stdout.strip()
        srv['status'] = status if status in ['active', 'inactive', 'failed'] else 'not_installed'

    try:
        from modsec_mgr import check_modsec_installed
        modsec_status = get_modsec_status()
        modsec_installed = check_modsec_installed()
        apache_active = any(s['id'] == 'apache2' and s['status'] == 'active' for s in services)
        if not modsec_installed:
            modsec_state = 'not_installed'
        elif modsec_status == 'Off':
            modsec_state = 'inactive'
        elif apache_active:
            modsec_state = 'active'
        else:
            modsec_state = 'inactive'
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

    if service_id == 'mongo-express':
        from mongodb_mgr import restart_mongo_express
        ok, msg = restart_mongo_express()
        return jsonify({'success': ok, 'message': msg})

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
