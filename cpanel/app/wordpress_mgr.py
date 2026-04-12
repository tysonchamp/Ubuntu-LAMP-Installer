import os
import subprocess
import secrets
import string
import json
import time
from database_mgr import create_database

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

def install_wordpress_generator(domain, target_path=""):
    def emit(progress, message, error=False, success=False):
        return json.dumps({
            "progress": progress,
            "message": message,
            "error": error,
            "success": success
        }) + "\n"

    try:
        yield emit(5, "Validating installation paths...")
        
        base_dir = f'/var/www/{domain}'
        if not target_path:
            doc_root = base_dir
        else:
            clean_target = os.path.normpath(f"/{target_path}").lstrip('/')
            doc_root = os.path.join(base_dir, clean_target)

        if not os.path.exists(base_dir):
            yield emit(100, f"Domain directory {base_dir} does not exist. Please create the virtual host first.", error=True)
            return
        
        os.makedirs(doc_root, exist_ok=True)

        if os.path.exists(os.path.join(doc_root, 'wp-config.php')):
            yield emit(100, f"WordPress is already installed in {doc_root}", error=True)
            return

        yield emit(15, "Checking WP-CLI utility...")
        if not subprocess.run(['command', '-v', 'wp'], shell=True, capture_output=True).stdout:
            yield emit(20, "Downloading & Installing WP-CLI...")
            # Download to tmp first, then move to avoid Text File Busy
            cmd = 'curl -sL https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar -o /tmp/wp-cli.phar && chmod +x /tmp/wp-cli.phar && mv /tmp/wp-cli.phar /usr/local/bin/wp && sync'
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if res.returncode != 0:
                yield emit(100, f"WP-CLI install failed: {res.stderr}", error=True)
                return

        time.sleep(0.5) # ensure sync propagation
        
        yield emit(35, "Generating secure database credentials...")
        db_name_base = domain.replace('.', '_').replace('-', '_')
        if target_path:
            db_name_base = f"{db_name_base}_{target_path.replace('/', '_')}"
        
        db_name = f"{db_name_base[:28]}_wp"
        db_user = f"{db_name_base[:12]}_usr"
        db_pass = generate_password()

        yield emit(45, f"Creating MySQL database `{db_name}`...")
        success, msg = create_database(db_name, db_user, db_pass)
        if not success:
            yield emit(100, f"Database creation failed: {msg}", error=True)
            return

        yield emit(55, "Removing standard index page if present...")
        default_index = os.path.join(doc_root, 'index.php')
        if os.path.exists(default_index):
            with open(default_index, 'r') as f:
                content = f.read()
                if 'WP_USE_THEMES' not in content:
                    os.remove(default_index)

        yield emit(65, "Downloading WordPress core via WP-CLI...")
        res = subprocess.run(['su', '-s', '/bin/bash', '-c', f'wp core download --path="{doc_root}"', 'www-data'], capture_output=True, text=True)
        if res.returncode != 0:
            yield emit(100, f"WordPress download failed: {res.stderr}", error=True)
            return

        yield emit(85, "Configuring wp-config.php integrations...")
        res = subprocess.run(['su', '-s', '/bin/bash', '-c', f'wp config create --dbname="{db_name}" --dbuser="{db_user}" --dbpass="{db_pass}" --path="{doc_root}"', 'www-data'], capture_output=True, text=True)
        if res.returncode != 0:
            yield emit(100, f"WordPress config creation failed: {res.stderr}", error=True)
            return

        yield emit(95, "Securing filesystem permissions...")
        subprocess.run(['chown', '-R', 'www-data:www-data', doc_root])
        subprocess.run(['chmod', '-R', '755', doc_root])

        yield emit(100, f"WordPress successfully installed in {doc_root}!", success=True)

    except Exception as e:
        yield emit(100, f"Unexpected error: {str(e)}", error=True)
