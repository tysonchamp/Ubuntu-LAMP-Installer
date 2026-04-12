import os
import subprocess
import json
import logging

# Define paths relative to this file
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
CONFIG_FILE = os.path.join(BASE_DIR, 'app', 'config.json')

def get_settings():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {"auto_update": False, "last_check": None}

def save_settings(settings):
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(settings, f, indent=4)
        return True
    except Exception:
        return False

def run_git(args):
    try:
        result = subprocess.run(
            ['git'] + args,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True
        )
        return True, result.stdout.strip()
    except subprocess.CalledProcessError as e:
        return False, e.stderr.strip()
    except Exception as e:
        return False, str(e)

def get_version_info():
    """Returns local hash, remote hash, and update availability."""
    success_local, local_hash = run_git(['rev-parse', 'HEAD'])
    
    # Try to fetch without blocking too long
    run_git(['fetch', '--quiet', 'origin'])
    
    # Get current branch
    _, branch = run_git(['rev-parse', '--abbrev-ref', 'HEAD'])
    
    success_remote, remote_hash = run_git(['rev-parse', f'origin/{branch}'])
    
    if not success_local or not success_remote:
        return {
            "local": local_hash if success_local else "Error",
            "remote": remote_hash if success_remote else "Error",
            "update_available": False,
            "branch": branch
        }
        
    return {
        "local": local_hash[:8],
        "remote": remote_hash[:8],
        "full_local": local_hash,
        "full_remote": remote_hash,
        "update_available": local_hash != remote_hash,
        "branch": branch
    }

def perform_update():
    """Performs git pull on the current branch."""
    # First, get the current branch name
    success_br, branch = run_git(['rev-parse', '--abbrev-ref', 'HEAD'])
    if not success_br:
        return False, f"Could not detect current branch: {branch}"
        
    success, output = run_git(['pull', 'origin', branch])
    if success:
        return True, f"Update pulled successfully for branch '{branch}'."
    return False, f"Pull failed: {output}"

def restart_service():
    """Triggers a systemd restart for the cPanel service."""
    try:
        # We use a detached process to ensure the restart command completes after this process dies
        subprocess.Popen(['systemctl', 'restart', 'cpanel'])
        return True, "Restarting service..."
    except Exception as e:
        return False, str(e)
