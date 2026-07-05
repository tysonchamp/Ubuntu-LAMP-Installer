import os
import subprocess
import shutil

def check_redis_installed():
    """Checks if redis-server is available in the system path."""
    return shutil.which('redis-server') is not None

def install_redis():
    """Installs Redis server using apt-get in the background."""
    install_script = """#!/bin/bash
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y redis-server
systemctl enable redis-server
systemctl start redis-server
"""
    try:
        script_path = '/tmp/install_redis.sh'
        with open(script_path, 'w') as f:
            f.write(install_script)
        os.chmod(script_path, 0o755)
        
        log_file = open('/var/log/lite-cpanel-redis-install.log', 'w')
        subprocess.Popen(['bash', script_path], stdout=log_file, stderr=subprocess.STDOUT)
        return True, "Redis installation started in the background. Please wait a few minutes."
    except Exception as e:
        return False, f"Failed to start installation: {e}"

def get_redis_status():
    """Returns 'active', 'inactive', or 'not_installed'."""
    if not check_redis_installed():
        return 'not_installed'
    try:
        r = subprocess.run(['systemctl', 'is-active', 'redis-server'], capture_output=True, text=True)
        status = r.stdout.strip()
        if status in ['active', 'inactive', 'failed']:
            return status
    except Exception:
        pass
    return 'inactive'

def _run_redis_cli(command):
    """Helper to run redis-cli commands. Uses the password from config if available."""
    cmd = ['redis-cli']
    password = _get_current_password()
    if password:
        cmd.extend(['-a', password])
    cmd.extend(command)
    try:
        # Suppress the warning about using password on command line interface
        return subprocess.run(cmd, capture_output=True, text=True, stderr=subprocess.DEVNULL)
    except Exception as e:
        class DummyRes:
            returncode = 1
            stdout = ""
        return DummyRes()

def _get_current_password():
    """Reads the current requirepass from redis.conf if it exists."""
    conf_path = '/etc/redis/redis.conf'
    if not os.path.exists(conf_path):
        return None
    try:
        with open(conf_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line.startswith('requirepass '):
                    return line.split(' ', 1)[1].strip('"\'')
    except Exception:
        pass
    return None

def get_redis_info():
    """Gets basic info from redis-cli."""
    if get_redis_status() != 'active':
        return None
    
    res = _run_redis_cli(['info'])
    if res.returncode != 0:
        return None
        
    info = {}
    for line in res.stdout.split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if ':' in line:
            key, val = line.split(':', 1)
            info[key] = val
    return info

def set_redis_password(new_password):
    """Sets the requirepass in redis.conf and restarts the server."""
    if not check_redis_installed():
        return False, "Redis is not installed."
        
    conf_path = '/etc/redis/redis.conf'
    if not os.path.exists(conf_path):
        return False, "redis.conf not found."
        
    try:
        # Read the file and update or append requirepass
        with open(conf_path, 'r') as f:
            lines = f.readlines()
            
        new_lines = []
        found = False
        for line in lines:
            if line.strip().startswith('requirepass '):
                if new_password:
                    new_lines.append(f'requirepass "{new_password}"\n')
                found = True
            else:
                new_lines.append(line)
                
        if not found and new_password:
            new_lines.append(f'requirepass "{new_password}"\n')
            
        with open(conf_path, 'w') as f:
            f.writelines(new_lines)
            
        # Restart the server to apply changes
        subprocess.run(['systemctl', 'restart', 'redis-server'], check=True)
        
        if new_password:
            return True, "Redis password set successfully."
        else:
            return True, "Redis password removed successfully."
    except Exception as e:
        return False, f"Failed to set password: {e}"

def flush_redis_db():
    """Flushes all databases in Redis."""
    if get_redis_status() != 'active':
        return False, "Redis is not running."
        
    res = _run_redis_cli(['flushall'])
    if res.returncode == 0:
        return True, "All databases flushed successfully."
    else:
        return False, f"Failed to flush databases. Check password."
