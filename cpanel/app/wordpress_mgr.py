import os
import subprocess
import secrets
import string

def generate_password(length=24):
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def get_installed_wordpress(vhosts):
    wp_domains = []
    for vhost in vhosts:
        domain = vhost.get('domain')
        if not domain: continue
        doc_root = f'/var/www/{domain}'
        if os.path.exists(os.path.join(doc_root, 'wp-config.php')):
            wp_domains.append({'domain': domain, 'path': doc_root})
        
        # Check subdirectories
        if os.path.exists(doc_root):
            try:
                for item in os.listdir(doc_root):
                    subpath = os.path.join(doc_root, item)
                    if os.path.isdir(subpath) and os.path.exists(os.path.join(subpath, 'wp-config.php')):
                        wp_domains.append({'domain': f'{domain}/{item}', 'path': subpath})
            except Exception:
                pass
    return wp_domains

def install_wordpress(domain, target_path=""):
    base_dir = f'/var/www/{domain}'
    
    if not target_path:
        doc_root = base_dir
    else:
        clean_target = os.path.normpath(f"/{target_path}").lstrip('/')
        doc_root = os.path.join(base_dir, clean_target)

    if not os.path.exists(base_dir):
        return False, f"Domain directory {base_dir} does not exist. Please create the virtual host first."
    
    os.makedirs(doc_root, exist_ok=True)

    if os.path.exists(os.path.join(doc_root, 'wp-config.php')):
        return False, f"WordPress is already installed in {doc_root}"

    if not subprocess.run(['command', '-v', 'wp'], shell=True, capture_output=True).stdout:
        subprocess.run('curl -sO https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar && chmod +x wp-cli.phar && mv wp-cli.phar /usr/local/bin/wp', shell=True)

    db_name_base = domain.replace('.', '_').replace('-', '_')
    if target_path:
        db_name_base = f"{db_name_base}_{target_path.replace('/', '_')}"
    
    db_name = f"{db_name_base[:28]}_wp"
    db_user = f"{db_name_base[:12]}_usr"
    db_pass = generate_password()

    mysql_script = f"""
    CREATE DATABASE IF NOT EXISTS `{db_name}`;
    CREATE USER IF NOT EXISTS '{db_user}'@'localhost' IDENTIFIED BY '{db_pass}';
    GRANT ALL PRIVILEGES ON `{db_name}`.* TO '{db_user}'@'localhost';
    FLUSH PRIVILEGES;
    """

    res = subprocess.run(['mysql', '-u', 'root'], input=mysql_script, text=True, capture_output=True)
    if res.returncode != 0:
        return False, f"Database creation failed: {res.stderr}"

    default_index = os.path.join(doc_root, 'index.php')
    if os.path.exists(default_index):
        with open(default_index, 'r') as f:
            content = f.read()
            if 'WP_USE_THEMES' not in content:
                os.remove(default_index)

    res = subprocess.run(['su', '-s', '/bin/bash', '-c', f'wp core download --path="{doc_root}"', 'www-data'], capture_output=True, text=True)
    if res.returncode != 0:
        return False, f"WordPress download failed: {res.stderr}"

    res = subprocess.run(['su', '-s', '/bin/bash', '-c', f'wp config create --dbname="{db_name}" --dbuser="{db_user}" --dbpass="{db_pass}" --path="{doc_root}"', 'www-data'], capture_output=True, text=True)
    if res.returncode != 0:
        return False, f"WordPress config creation failed: {res.stderr}"

    subprocess.run(['chown', '-R', 'www-data:www-data', doc_root])
    subprocess.run(['chmod', '-R', '755', doc_root])

    pass_file = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../scripts/.passwords'))
    domain_display = domain if not target_path else f"{domain}/{target_path}"
    
    try:
        with open(pass_file, 'a') as f:
            f.write(f"\nWordPress ({domain_display}):\n")
            f.write(f"DB Name: {db_name}\n")
            f.write(f"DB User: {db_user}\n")
            f.write(f"DB Pass: {db_pass}\n")
    except Exception as e:
        return True, f"WordPress installed successfully in {doc_root}, but failed to save passwords: {str(e)}"

    return True, f"WordPress installed successfully in {doc_root}"
