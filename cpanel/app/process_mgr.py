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
        # Check if it's a standard next.js app (has package.json)
        pkg_json = os.path.join(app_path, 'package.json')
        if not os.path.exists(pkg_json):
            return False, "No package.json found in the specified path."

        # Command to start: npm start -- -p PORT
        # We run it from the app directory
        cmd = [
            'pm2', 'start', 'npm', 
            '--name', app_name, 
            '--', 'start', '--', '-p', str(port)
        ]
        
        subprocess.run(cmd, cwd=app_path, check=True, capture_output=True, text=True)
        # Save to ensure it persists across reboots
        subprocess.run(['pm2', 'save'], check=True)
        
        return True, f"Application '{app_name}' started on port {port}."
    except subprocess.CalledProcessError as e:
        return False, f"Failed to start app: {e.stderr.strip()}"

def get_process_logs(name, lines=100):
    """Fetches the latest logs for a specific process."""
    try:
        # pm2 logs --lines N --nostream name
        result = subprocess.run(['pm2', 'logs', name, '--lines', str(lines), '--nostream'], 
                                capture_output=True, text=True, check=True)
        return result.stdout
    except Exception as e:
        return f"Error fetching logs: {str(e)}"
