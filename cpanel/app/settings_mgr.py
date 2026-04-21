import os
import subprocess

import glob

def get_system_logs():
    """
    Returns a dictionary of available common system logs, including vhosts, and their recent contents.
    """
    logs = {
        'Apache Error': '/var/log/apache2/error.log',
        'Apache Access': '/var/log/apache2/access.log',
        'Nginx Error': '/var/log/nginx/error.log',
        'Nginx Access': '/var/log/nginx/access.log',
        'Syslog': '/var/log/syslog',
        'MySQL Error': '/var/log/mysql/error.log',
        'Backup Log': '/var/log/lite-cpanel-backup.log',
        'Mongo Express': '/var/log/mongo-express.log',
        'Letsencrypt': '/var/log/letsencrypt/letsencrypt.log'
    }

    # Alternative paths for some services
    alt_paths = {
        'MySQL Error': ['/var/log/mariadb/mariadb.log', '/var/log/mysql/mariadb.log']
    }

    # Automatically add Apache vhost logs
    for log_path in glob.glob('/var/log/apache2/*-error.log'):
        name = os.path.basename(log_path).replace('-error.log', ' (Apache Error)')
        logs[name] = log_path

    for log_path in glob.glob('/var/log/apache2/*-access.log'):
        name = os.path.basename(log_path).replace('-access.log', ' (Apache Access)')
        logs[name] = log_path

    # Automatically add Nginx vhost logs
    for log_path in glob.glob('/var/log/nginx/*-error.log'):
        name = os.path.basename(log_path).replace('-error.log', ' (Nginx Error)')
        logs[name] = log_path

    results = {}
    core_log_names = ['Apache Error', 'Apache Access', 'Nginx Error', 'Nginx Access', 'Syslog', 'MySQL Error', 'Backup Log', 'Mongo Express', 'Letsencrypt']

    for name, path in logs.items():
        actual_path = path
        exists = os.path.exists(path)
        
        # Try alternatives if not found
        if not exists and name in alt_paths:
            for alt in alt_paths[name]:
                if os.path.exists(alt):
                    actual_path = alt
                    exists = True
                    break
        
        if exists:
            try:
                # Get last 100 lines
                result = subprocess.run(['tail', '-n', '100', actual_path], capture_output=True, text=True)
                if result.returncode == 0:
                    results[name] = {
                        'path': actual_path,
                        'content': result.stdout if result.stdout else "(Log file is empty)"
                    }
                else:
                    results[name] = {
                        'path': actual_path,
                        'content': f"Error reading log: {result.stderr}"
                    }
            except Exception as e:
                results[name] = {'path': actual_path, 'content': f"Error reading log: {str(e)}"}
        elif name in core_log_names:
            # Always show core logs even if missing
            results[name] = {
                'path': actual_path,
                'content': "Log file does not exist yet. This service may not have generated any logs, or the feature is not in use."
            }

    return results

def get_editable_configs():
    """
    Returns a list of common configuration files, including vhosts, that can be edited.
    """
    configs = []
    potential_configs = [
        ('/etc/php/8.1/apache2/php.ini', 'PHP 8.1 Apache config'),
        ('/etc/php/8.1/fpm/php.ini', 'PHP 8.1 FPM config'),
        ('/etc/apache2/apache2.conf', 'Main Apache config'),
        ('/etc/nginx/nginx.conf', 'Main Nginx config'),
        ('/etc/mysql/mariadb.conf.d/50-server.cnf', 'MariaDB Server config'),
        ('/etc/pure-ftpd/pure-ftpd.conf', 'Pure-FTPd config')
    ]

    for path, name in potential_configs:
        if os.path.exists(path):
            configs.append({'path': path, 'name': name})

    return configs

def read_config_file(filepath):
    # Security check: only allow reading specific known files to prevent arbitrary file read
    valid_paths = [c['path'] for c in get_editable_configs()]
    if filepath not in valid_paths:
        return False, "File is not in the allowed list for editing."

    try:
        with open(filepath, 'r') as f:
            return True, f.read()
    except Exception as e:
        return False, str(e)

def save_config_file(filepath, content):
    # Security check: only allow writing specific known files
    valid_paths = [c['path'] for c in get_editable_configs()]
    if filepath not in valid_paths:
        return False, "File is not in the allowed list for editing."

    try:
        with open(filepath, 'w') as f:
            f.write(content)

        # Try to reload the relevant service based on the file edited
        if 'apache2' in filepath:
            subprocess.run(['systemctl', 'reload', 'apache2'])
        elif 'nginx' in filepath:
            subprocess.run(['systemctl', 'reload', 'nginx'])
        elif 'php' in filepath and 'fpm' in filepath:
            subprocess.run(['systemctl', 'reload', 'php8.1-fpm'])

        return True, "File saved successfully and service reloaded."
    except Exception as e:
        return False, str(e)
