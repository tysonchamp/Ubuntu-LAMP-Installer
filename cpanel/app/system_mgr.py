import os
import subprocess
import json
import psutil
import platform
import socket
import datetime
import threading
import time
import re
from datetime import datetime as dt_class

# --- Global Cache for Dashboard Speed ---
DASHBOARD_CACHE = {
    'traffic': [],
    'security_events': [],
    'public_ip': "Unknown",
    'cpu_model': "Unknown",
    'last_ip_update': 0,
    'last_traffic_update': 0,
    'last_security_update': 0
}

def get_cpu_model():
    try:
        if os.path.exists('/proc/cpuinfo'):
            with open('/proc/cpuinfo', 'r') as f:
                for line in f:
                    if 'model name' in line:
                        return line.split(':')[1].strip()
    except: pass
    return platform.processor() or "Generic Processor"

def get_dashboard_traffic():
    """Heavy function to calculate traffic for all domains."""
    from nextjs_mgr import get_nextjs_apps
    from domains_mgr import get_virtual_hosts
    
    traffic_stats = []
    all_domains = set()
    try:
        for app in get_nextjs_apps(): all_domains.add(app['domain'])
        for host in get_virtual_hosts(): all_domains.add(host['domain'])
    except: pass

    for domain in all_domains:
        domain_lower = domain.lower()
        log_candidates = [
            f"/var/log/nginx/{domain_lower}_access.log",
            f"/var/log/apache2/{domain_lower}_access.log",
            f"/var/log/nginx/{domain_lower}.access.log",
            f"/var/log/apache2/{domain_lower}.access.log",
            f"/var/log/nginx/access.log",
        ]
        
        traffic_item = None
        for log_file in log_candidates:
            if os.path.exists(log_file):
                try:
                    cmd = ['/usr/bin/goaccess', log_file, '--log-format=COMBINED', '--no-global-config', '-o', 'json']
                    res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                    if res.returncode == 0:
                        data = json.loads(res.stdout)
                        gen = data.get('general', {})
                        traffic_item = {
                            'domain': domain, 
                            'hits': gen.get('total_requests', 0), 
                            'bandwidth': gen.get('bandwidth', 0), 
                            'visitors': gen.get('unique_visitors', 0)
                        }
                        if traffic_item['hits'] > 0: break
                except: pass
        if traffic_item: traffic_stats.append(traffic_item)
    return sorted(traffic_stats, key=lambda x: x['bandwidth'], reverse=True)

def get_dashboard_security():
    """Heavy function to parse security logs."""
    all_events = []
    auth_logs = [('/var/log/auth.log', 'sshd'), ('/var/log/secure', 'sshd'), ('/var/log/cpanel_auth.log', 'cpanel_auth')]
    
    for log_path, tag in auth_logs:
        if os.path.exists(log_path):
            try:
                res = subprocess.run(['tail', '-n', '50', log_path], capture_output=True, text=True, timeout=5)
                for line in res.stdout.strip().split('\n'):
                    if not line: continue
                    if (tag == 'sshd' and any(x in line for x in ['Accepted', 'Failed', 'Invalid'])) or \
                       (tag == 'cpanel_auth' and 'Failed login attempt' in line):
                        
                        time_str = "Unknown"
                        iso_match = re.search(r'^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})', line)
                        if iso_match:
                            try:
                                dt = dt_class.strptime(f"{iso_match.group(1)} {iso_match.group(2)}", '%Y-%m-%d %H:%M:%S')
                                time_str = dt.strftime('%b %d %H:%M:%S')
                            except: time_str = f"{iso_match.group(1)} {iso_match.group(2)}"
                        else:
                            syslog_match = re.match(r'^(\w{3}\s+\d+\s+\d{2}:\d{2}:\d{2})', line)
                            if syslog_match:
                                time_str = syslog_match.group(1)
                            else:
                                time_str = " ".join(line.split()[:3])

                        m = re.search(r'sshd\[\d+\]: (.*)', line)
                        if not m and 'cpanel_auth' in tag:
                            m = re.search(r'cpanel_auth: (.*)', line)
                        msg = m.group(1) if m else line
                        
                        all_events.append({'time': time_str, 'msg': msg})
            except: pass
    return sorted(all_events, key=lambda x: x['time'], reverse=True)[:10]

def dashboard_background_worker():
    """Background worker to pre-calculate heavy dashboard stats."""
    DASHBOARD_CACHE['cpu_model'] = get_cpu_model()
    
    while True:
        try:
            # 1. Update Public IP (every 24h)
            if time.time() - DASHBOARD_CACHE['last_ip_update'] > 86400:
                try:
                    import urllib.request
                    DASHBOARD_CACHE['public_ip'] = urllib.request.urlopen('https://ident.me', timeout=5).read().decode('utf-8').strip()
                    DASHBOARD_CACHE['last_ip_update'] = time.time()
                except: pass

            # 2. Update Traffic (every 10 min)
            if time.time() - DASHBOARD_CACHE['last_traffic_update'] > 600:
                DASHBOARD_CACHE['traffic'] = get_dashboard_traffic()
                DASHBOARD_CACHE['last_traffic_update'] = time.time()

            # 3. Update Security Events (every 2 min)
            if time.time() - DASHBOARD_CACHE['last_security_update'] > 120:
                DASHBOARD_CACHE['security_events'] = get_dashboard_security()
                DASHBOARD_CACHE['last_security_update'] = time.time()
                
        except Exception as e:
            print(f"Background worker error: {e}")
        time.sleep(30)

def start_background_workers():
    threading.Thread(target=dashboard_background_worker, daemon=True).start()

def get_system_stats():
    """Returns real-time system metrics."""
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    return {
        'cpu': psutil.cpu_percent(interval=None),
        'ram_total': round(ram.total / (1024**3), 2),
        'ram_used': round(ram.used / (1024**3), 2),
        'ram_percent': ram.percent,
        'disk_total': round(disk.total / (1024**3), 2),
        'disk_used': round(disk.used / (1024**3), 2),
        'disk_percent': disk.percent
    }

def get_server_info():
    """Returns detailed server information."""
    boot_time = datetime.datetime.fromtimestamp(psutil.boot_time())
    uptime_delta = datetime.datetime.now() - boot_time
    uptime_str = f"{uptime_delta.days}d {uptime_delta.seconds // 3600}h {(uptime_delta.seconds % 3600) // 60}m"

    # Fast IP detection
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip_address = s.getsockname()[0]
        s.close()
    except: ip_address = "Unknown"

    ports = []
    try:
        for conn in psutil.net_connections(kind='inet'):
            if conn.status == 'LISTEN': ports.append(conn.laddr.port)
        ports = sorted(list(set(ports)))
    except: pass

    return {
        'hostname': platform.node(),
        'ip_address': ip_address,
        'public_ip': DASHBOARD_CACHE.get('public_ip', 'Unknown'),
        'processor': DASHBOARD_CACHE.get('cpu_model', 'Unknown'),
        'cpu_cores': psutil.cpu_count(logical=True),
        'cpu_freq': f"{psutil.cpu_freq().current:.0f} MHz" if psutil.cpu_freq() else "N/A",
        'os': "Linux",
        'kernel': platform.release(),
        'platform': f"{platform.machine()} {platform.system()}",
        'uptime': uptime_str,
        'server_time': datetime.datetime.now().strftime("%a %b %d %H:%M:%S"),
        'listening_ports': ports,
        'ssh_logins': DASHBOARD_CACHE.get('security_events', [])
    }

def get_process_list(limit=10):
    """Returns the top processes by CPU usage."""
    res = subprocess.run(['ps', 'aux', '--sort=-%cpu'], capture_output=True, text=True)
    lines = res.stdout.strip().split('\n')
    processes = []
    for line in lines[1:limit+1]:
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
    return processes

def get_services_status():
    """Returns status of all managed services."""
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

    # ModSecurity logic
    try:
        from modsec_mgr import get_modsec_status, check_modsec_installed
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

    return services

def restart_system_service(service_id):
    """Restarts a system service safely."""
    if service_id == 'mongo-express':
        from mongodb_mgr import restart_mongo_express
        return restart_mongo_express()

    if service_id == 'modsec':
        res = subprocess.run(['systemctl', 'restart', 'apache2'], capture_output=True, text=True)
        if res.returncode == 0:
            return True, 'ModSecurity refreshed successfully.'
        return False, f'Operation failed: {res.stderr}'

    if service_id == 'cpanel':
        subprocess.Popen(['bash', '-c', 'sleep 1 && systemctl restart cpanel.service'])
        return True, 'Process initiated in background...'

    if service_id not in ['apache2', 'nginx', 'mariadb', 'mysql', 'csf'] and not service_id.startswith('php'):
        return False, 'Forbidden infrastructure target.'

    res = subprocess.run(['systemctl', 'restart', service_id], capture_output=True, text=True)
    if res.returncode == 0:
        return True, f'{service_id.title()} has been restarted successfully.'
    else:
        return False, f'Crash/Timeout: {res.stderr}'
