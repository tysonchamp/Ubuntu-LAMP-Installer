import os
import subprocess

def get_system_logs():
    """
    Returns a dictionary of available common system logs and their recent contents.
    """
    logs = {
        'Apache Error': '/var/log/apache2/error.log',
        'Nginx Error': '/var/log/nginx/error.log',
        'Syslog': '/var/log/syslog',
        'MySQL Error': '/var/log/mysql/error.log'
    }

    results = {}
    for name, path in logs.items():
        if os.path.exists(path):
            try:
                # Get last 100 lines
                result = subprocess.run(['tail', '-n', '100', path], capture_output=True, text=True)
                results[name] = {
                    'path': path,
                    'content': result.stdout
                }
            except Exception as e:
                results[name] = {'path': path, 'content': f"Error reading log: {str(e)}"}

    return results

def get_editable_configs():
    """
    Returns a list of common configuration files that can be edited.
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
