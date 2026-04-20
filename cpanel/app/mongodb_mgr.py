import os
import subprocess
try:
    import pymongo
except ImportError:
    pymongo = None

def check_mongodb_installed():
    import shutil
    return shutil.which('mongod') is not None

def install_mongodb():
    install_script = """#!/bin/bash
export DEBIAN_FRONTEND=noninteractive
apt-get install gnupg curl -y
curl -fsSL https://www.mongodb.org/static/pgp/server-8.0.asc | gpg -o /usr/share/keyrings/mongodb-server-8.0.gpg --dearmor --yes
echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-8.0.gpg ] https://repo.mongodb.org/apt/ubuntu noble/mongodb-org/8.2 multiverse" > /etc/apt/sources.list.d/mongodb-org-8.2.list
apt-get update
apt-get install -y mongodb-org php-pear php-mongodb
systemctl enable mongod
systemctl start mongod
"""
    try:
        script_path = '/tmp/install_mongo.sh'
        with open(script_path, 'w') as f:
            f.write(install_script)
        os.chmod(script_path, 0o755)
        
        log_file = open('/var/log/lite-cpanel-mongo-install.log', 'w')
        subprocess.Popen(['bash', script_path], stdout=log_file, stderr=subprocess.STDOUT)
        return True, "MongoDB installation started in the background. Please wait a few minutes."
    except Exception as e:
        return False, f"Failed to start installation: {e}"

def get_mongo_client():
    if not pymongo:
        return None
    try:
        client = pymongo.MongoClient('mongodb://127.0.0.1:27017/', serverSelectionTimeoutMS=2000)
        client.admin.command('ping')
        return client
    except Exception:
        return None

def get_databases():
    client = get_mongo_client()
    if not client: return []
    try:
        system_dbs = ('admin', 'config', 'local')
        
        # Get databases that have actual data
        listed_dbs = set(client.list_database_names()) - set(system_dbs)
        
        # Also discover databases that only have users but no data yet
        # by scanning admin.system.users
        try:
            all_users = client['admin'].system.users.find({}, {'db': 1, 'user': 1})
            for u in all_users:
                if u.get('db') not in system_dbs:
                    listed_dbs.add(u['db'])
        except Exception:
            pass
        
        result = []
        for db_name in sorted(listed_dbs):
            try:
                db_obj = client[db_name]
                users_info = db_obj.command("usersInfo")
                users = [{'User': u['user']} for u in users_info.get('users', [])]
                
                try:
                    stats = db_obj.command("dbStats")
                    size_mb = round(stats.get('dataSize', 0) / (1024 * 1024), 2)
                except Exception:
                    size_mb = 0
                
                result.append({
                    'name': db_name,
                    'users': users,
                    'size_mb': size_mb
                })
            except Exception:
                result.append({
                    'name': db_name,
                    'users': [],
                    'size_mb': 0
                })
        return result
    except Exception:
        return []

def create_database(db_name, db_user, db_pass):
    client = get_mongo_client()
    if not client: return False, "Could not connect to MongoDB."
    try:
        db = client[db_name]
        db.command("createUser", db_user, pwd=db_pass, roles=["dbOwner"])
        # Insert a metadata doc so the database actually materializes
        # (MongoDB won't show a DB in list_database_names until it has data)
        db['_init'].insert_one({'_created_by': 'lite-cpanel', 'info': 'initial collection'})
        return True, "Database and user created successfully."
    except Exception as e:
        return False, f"Error: {str(e)}"

def delete_database(db_name):
    client = get_mongo_client()
    if not client: return False, "Could not connect to MongoDB."
    try:
        client.drop_database(db_name)
        return True, "Database deleted successfully."
    except Exception as e:
        return False, f"Error: {str(e)}"

def change_user_password(db_name, db_user, new_password):
    client = get_mongo_client()
    if not client: return False, "Could not connect to MongoDB."
    try:
        db = client[db_name]
        db.command("updateUser", db_user, pwd=new_password)
        return True, f"Password updated for {db_user}."
    except Exception as e:
        return False, f"Error: {str(e)}"


# --- Mongo Express Management ---

MONGO_EXPRESS_PORT = 8081
MONGO_EXPRESS_SERVICE = 'mongo-express'
MONGO_EXPRESS_CONFIG = '/etc/mongo-express.config.js'

def check_mongo_express_installed():
    """Check if mongo-express is installed globally via npm or nvm."""
    import shutil
    if shutil.which('mongo-express'):
        return True
    home = os.path.expanduser("~")
    nvm_dir = os.path.join(home, ".nvm", "versions", "node")
    if os.path.exists(nvm_dir):
        for version in os.listdir(nvm_dir):
            if os.path.exists(os.path.join(nvm_dir, version, 'bin', 'mongo-express')):
                return True
    return False

def get_mongo_express_status():
    """Returns 'active', 'inactive', or 'not_installed'."""
    if not check_mongo_express_installed():
        return 'not_installed'
    try:
        res = subprocess.run(['systemctl', 'is-active', MONGO_EXPRESS_SERVICE],
                             capture_output=True, text=True)
        status = res.stdout.strip()
        return status if status in ('active', 'inactive', 'failed') else 'inactive'
    except Exception:
        return 'inactive'

def install_mongo_express():
    """Install mongo-express via nvm/npm, create config, systemd service, and Apache proxy."""
    try:
        # 1. Install nvm, node 24, and mongo-express
        install_script = """#!/bin/bash
export NVM_DIR="$HOME/.nvm"

# Check if node is installed globally
if ! command -v node &> /dev/null && [ ! -s "$NVM_DIR/nvm.sh" ]; then
    curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.4/install.sh | bash
fi

if [ -s "$NVM_DIR/nvm.sh" ]; then
    \\. "$NVM_DIR/nvm.sh"
    # Only install 24 if node isn't already installed via NVM
    if ! command -v node &> /dev/null || [[ ! "$(node -v)" == v24* ]]; then
        nvm install 24
    fi
    nvm use 24
fi

npm install -g mongo-express
"""
        res = subprocess.run(['bash', '-c', install_script], capture_output=True, text=True, timeout=300)
        if res.returncode != 0:
            return False, f"Installation via NVM failed: {res.stderr}"

        # 2. Get the paths to node and mongo-express app.js
        get_paths_script = """#!/bin/bash
export NVM_DIR="$HOME/.nvm"
\\. "$NVM_DIR/nvm.sh"
nvm use 24 > /dev/null 2>&1
which node
npm root -g
"""
        res_paths = subprocess.run(['bash', '-c', get_paths_script], capture_output=True, text=True)
        paths = res_paths.stdout.strip().split('\\n')
        if len(paths) >= 2:
            node_bin = paths[-2].strip()
            npm_root = paths[-1].strip()
        else:
            return False, "Failed to resolve node/npm paths after installation."

        me_app_js = os.path.join(npm_root, 'mongo-express', 'app.js')
        if not os.path.exists(me_app_js):
            return False, f"mongo-express app.js not found at {me_app_js}."

        # 3. Create config file
        import secrets
        admin_pass = secrets.token_urlsafe(16)
        config_content = f"""'use strict';

var mongo = {{
  db: 'admin',
  host: '127.0.0.1',
  port: 27017,
  username: '',
  password: '',
  url: 'mongodb://127.0.0.1:27017',
  ssl: false,
  autoReconnect: true,
  poolSize: 4,
  admin: true,
}};

var basicAuth = {{
  username: 'admin',
  password: '{admin_pass}',
}};

var options = {{
  console: true,
  documentsPerPage: 50,
  editorTheme: 'rubyblue',
  maxPropSize: (100 * 1000),
  maxRowSize: (1000 * 1000),
  cmdType: 'eval',
  subprocessTimeout: 300,
  readOnly: false,
  collapsibleJSON: true,
  collapsibleJSONDefaultUnfold: 1,
  noExport: false,
  noDelete: false,
  confirmDelete: true,
}};

var site = {{
  baseUrl: '/mongo-express',
  cookieKeyName: 'mongo-express',
  cookieSecret: '{secrets.token_hex(32)}',
  host: '127.0.0.1',
  port: {MONGO_EXPRESS_PORT},
  requestSizeLimit: '50mb',
  sslEnabled: false,
}};

module.exports = {{
  mongodb: mongo,
  basicAuth: basicAuth,
  options: options,
  site: site,
  useBasicAuth: true,
}};
"""
        with open(MONGO_EXPRESS_CONFIG, 'w') as f:
            f.write(config_content)
        os.chmod(MONGO_EXPRESS_CONFIG, 0o600)

        # Save credentials for reference
        creds_file = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../scripts/.mongo_express_creds'))
        with open(creds_file, 'w') as f:
            f.write(f"Mongo Express Admin Username: admin\\n")
            f.write(f"Mongo Express Admin Password: {admin_pass}\\n")
        os.chmod(creds_file, 0o600)

        # 4. Create systemd service
        service_content = f"""[Unit]
Description=Mongo Express Web Admin
After=network.target mongod.service

[Service]
Type=simple
ExecStart={node_bin} {me_app_js} -c {MONGO_EXPRESS_CONFIG}
Restart=on-failure
RestartSec=5
Environment=NODE_ENV=production
Environment=ME_CONFIG_FILE={MONGO_EXPRESS_CONFIG}
User=root

[Install]
WantedBy=multi-user.target
"""
        service_path = f'/etc/systemd/system/{MONGO_EXPRESS_SERVICE}.service'
        with open(service_path, 'w') as f:
            f.write(service_content)

        subprocess.run(['systemctl', 'daemon-reload'], check=True)
        subprocess.run(['systemctl', 'enable', MONGO_EXPRESS_SERVICE], check=True)
        subprocess.run(['systemctl', 'start', MONGO_EXPRESS_SERVICE], check=True)

        # 5. Setup Apache reverse proxy
        _setup_apache_proxy()

        return True, "Mongo Express installed and started successfully!"
    except subprocess.TimeoutExpired:
        return False, "Installation timed out. Please try again."
    except Exception as e:
        return False, f"Installation failed: {str(e)}"

def _setup_apache_proxy():
    """Add Apache ProxyPass for /mongo-express to the default site config."""
    conf_path = '/etc/apache2/conf-available/mongo-express.conf'
    content = f"""# Mongo Express Reverse Proxy
<Location /mongo-express>
    ProxyPass http://127.0.0.1:{MONGO_EXPRESS_PORT}/mongo-express
    ProxyPassReverse http://127.0.0.1:{MONGO_EXPRESS_PORT}/mongo-express
</Location>
"""
    with open(conf_path, 'w') as f:
        f.write(content)

    # Enable proxy modules and the config
    subprocess.run(['a2enmod', 'proxy'], capture_output=True)
    subprocess.run(['a2enmod', 'proxy_http'], capture_output=True)
    subprocess.run(['a2enconf', 'mongo-express'], capture_output=True)
    subprocess.run(['systemctl', 'reload', 'apache2'], capture_output=True)

def restart_mongo_express():
    """Restart the mongo-express systemd service."""
    try:
        subprocess.run(['systemctl', 'restart', MONGO_EXPRESS_SERVICE], check=True)
        return True, "Mongo Express restarted successfully."
    except Exception as e:
        return False, f"Failed to restart: {str(e)}"

def get_mongo_express_credentials():
    """Read saved Mongo Express credentials."""
    creds_file = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../scripts/.mongo_express_creds'))
    creds = {'username': 'admin', 'password': ''}
    if os.path.exists(creds_file):
        with open(creds_file, 'r') as f:
            for line in f:
                if 'Username:' in line:
                    creds['username'] = line.split(':', 1)[1].strip()
                elif 'Password:' in line:
                    creds['password'] = line.split(':', 1)[1].strip()
    return creds

