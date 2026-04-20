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
