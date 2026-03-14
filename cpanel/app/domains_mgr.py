import os
import subprocess

def get_virtual_hosts():
    """
    Returns a list of dictionaries with virtual host information.
    Checks both Nginx and Apache directories.
    """
    vhosts = []

    # Check Nginx
    nginx_dir = '/etc/nginx/sites-available'
    if os.path.exists(nginx_dir):
        for f in os.listdir(nginx_dir):
            if f != 'default':
                enabled = os.path.exists(f'/etc/nginx/sites-enabled/{f}')
                vhosts.append({
                    'server': 'Nginx',
                    'domain': f,
                    'enabled': enabled,
                    'config_path': os.path.join(nginx_dir, f)
                })

    # Check Apache
    apache_dir = '/etc/apache2/sites-available'
    if os.path.exists(apache_dir):
        for f in os.listdir(apache_dir):
            if f != '000-default.conf' and f != 'default-ssl.conf':
                domain = f.replace('.conf', '')
                enabled = os.path.exists(f'/etc/apache2/sites-enabled/{f}')
                vhosts.append({
                    'server': 'Apache',
                    'domain': domain,
                    'enabled': enabled,
                    'config_path': os.path.join(apache_dir, f)
                })

    return vhosts

def add_virtual_host(domain):
    """
    Calls the existing vhost-manager.sh script to create a new virtual host.
    """
    # Try to find the script in the parent directory
    script_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'vhost-manager.sh')

    if os.path.exists(script_path):
        try:
            # We assume it's run as root, so we just execute it directly
            result = subprocess.run([script_path, 'create', domain],
                                  capture_output=True, text=True, check=True)
            return True, "Virtual host created successfully."
        except subprocess.CalledProcessError as e:
            return False, f"Error creating virtual host: {e.stderr}"
    else:
        # Fallback if the script isn't found
        return False, "vhost-manager.sh script not found."

def toggle_virtual_host(domain, server, enable):
    """
    Enables or disables a virtual host.
    """
    try:
        if server == 'Nginx':
            config_file = domain
            enabled_link = f'/etc/nginx/sites-enabled/{config_file}'
            if enable:
                os.symlink(f'/etc/nginx/sites-available/{config_file}', enabled_link)
            else:
                os.remove(enabled_link)
            subprocess.run(['systemctl', 'reload', 'nginx'], check=True)
            return True, f"Domain {domain} {'enabled' if enable else 'disabled'} successfully."

        elif server == 'Apache':
            config_file = f"{domain}.conf"
            cmd = ['a2ensite', config_file] if enable else ['a2dissite', config_file]
            subprocess.run(cmd, check=True, capture_output=True)
            subprocess.run(['systemctl', 'reload', 'apache2'], check=True)
            return True, f"Domain {domain} {'enabled' if enable else 'disabled'} successfully."

    except Exception as e:
        return False, f"Error: {str(e)}"

    return False, "Unknown server type."
