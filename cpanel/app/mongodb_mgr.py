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
        db_names = client.list_database_names()
        result = []
        for db in db_names:
            if db in ('admin', 'config', 'local'):
                continue
            
            db_obj = client[db]
            users_info = db_obj.command("usersInfo")
            users = [{'User': u['user']} for u in users_info.get('users', [])]
            
            stats = db_obj.command("dbStats")
            size_mb = round(stats.get('dataSize', 0) / (1024 * 1024), 2)
            
            result.append({
                'name': db,
                'users': users,
                'size_mb': size_mb
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
