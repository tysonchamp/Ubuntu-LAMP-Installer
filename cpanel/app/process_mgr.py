import subprocess
import json
import os
import shutil

def is_pm2_installed():
    """Checks if PM2 is available in the system path."""
    return shutil.which('pm2') is not None

def install_pm2():
    """Attempts to install PM2 globally via npm."""
    try:
        # We assume npm is installed as part of the Node.js requirement for Next.js
        subprocess.run(['npm', 'install', '-g', 'pm2'], check=True, capture_output=True, text=True)
        return True, "PM2 installed successfully."
    except Exception as e:
        return False, f"Failed to install PM2: {str(e)}"

def list_processes():
    """Returns a list of running PM2 processes in JSON format."""
    if not is_pm2_installed():
        return []
    
    try:
        result = subprocess.run(['pm2', 'jlist'], capture_output=True, text=True, check=True)
        return json.loads(result.stdout)
    except Exception:
        return []

def manage_process(action, name_or_id):
    """
    Performs an action (start, stop, restart, delete) on a PM2 process.
    """
    if action not in ['start', 'stop', 'restart', 'delete']:
        return False, "Invalid action."
    
    try:
        subprocess.run(['pm2', action, str(name_or_id)], check=True, capture_output=True, text=True)
        return True, f"Process {action}ed successfully."
    except subprocess.CalledProcessError as e:
        return False, f"Error: {e.stderr.strip()}"

def start_nextjs_app(app_path, app_name, port):
    """
    Starts a Next.js application using PM2.
    """
    if not os.path.exists(app_path):
        return False, f"Path does not exist: {app_path}"
    
    try:
        # Check for ecosystem.config.js (Prioritize)
        ecosystem_path = os.path.join(app_path, 'ecosystem.config.js')
        if os.path.exists(ecosystem_path):
            cmd = ['pm2', 'start', 'ecosystem.config.js', '--name', app_name]
        else:
            # Check if it's a standard next.js app (has package.json)
            pkg_json = os.path.join(app_path, 'package.json')
            if not os.path.exists(pkg_json):
                return False, "No package.json or ecosystem.config.js found in the specified path."
            
            # Command to start: npm start -- -p PORT
            if not port:
                return False, "Port is required when no ecosystem.config.js is found."
            
            cmd = [
                'pm2', 'start', 'npm', 
                '--name', app_name, 
                '--', 'start', '--', '-p', str(port)
            ]
        
        subprocess.run(cmd, cwd=app_path, check=True, capture_output=True, text=True)
        # Save to ensure it persists across reboots
        subprocess.run(['pm2', 'save'], check=True)
        
        return True, f"Application '{app_name}' started successfully."
    except subprocess.CalledProcessError as e:
        return False, f"Failed to start app: {e.stderr.strip()}"

def run_npm_command(app_path, command):
    """
    Runs an npm command (install or build) in the specified directory.
    """
    if command not in ['install', 'run build']:
        return False, "Invalid npm command."
    
    if not os.path.exists(app_path):
        return False, f"Path does not exist: {app_path}"
    
    try:
        # We use a longer timeout for builds
        cmd = ['npm'] + command.split()
        result = subprocess.run(cmd, cwd=app_path, capture_output=True, text=True, check=True)
        return True, f"npm {command} completed successfully."
    except subprocess.CalledProcessError as e:
        return False, f"npm {command} failed: {e.stderr.strip() or e.stdout.strip()}"
    except Exception as e:
        return False, f"An error occurred: {str(e)}"

def get_process_logs(name, lines=100):
    """Fetches the latest logs for a specific process."""
    try:
        # pm2 logs --lines N --nostream name
        result = subprocess.run(['pm2', 'logs', name, '--lines', str(lines), '--nostream'], 
                                capture_output=True, text=True, check=True)
        return result.stdout
    except Exception as e:
        return f"Error fetching logs: {str(e)}"
