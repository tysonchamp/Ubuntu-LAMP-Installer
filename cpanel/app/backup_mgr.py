import os
import json
import subprocess
from datetime import datetime
from cron_mgr import get_raw_crontab, write_raw_crontab

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, 'backup_config.json')
BACKUP_DIR = '/backup'

def get_backup_settings():
    default_settings = {
        "local_enabled": True,
        "ftp_enabled": False,
        "ftp_host": "",
        "ftp_port": "21",
        "ftp_user": "",
        "ftp_pass": "",
        "ftp_path": "/",
        "s3_enabled": False,
        "s3_endpoint": "https://sfo3.digitaloceanspaces.com",
        "s3_access_key": "",
        "s3_secret_key": "",
        "s3_bucket": "",
        "s3_region": "sfo3",
        "retention_days": 7,
        "schedule": "0 2 * * *"
    }
    
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                settings = json.load(f)
                # Merge defaults to handle missing keys
                default_settings.update(settings)
        except Exception:
            pass
            
    return default_settings

def save_backup_settings(settings):
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(settings, f, indent=4)
            
        _update_backup_cron(settings['schedule'])
        return True, "Backup settings saved successfully."
    except Exception as e:
        return False, f"Failed to save settings: {str(e)}"

def _update_backup_cron(schedule):
    """Adds or updates the backup cron job in the system crontab."""
    lines = get_raw_crontab()
    new_lines = []
    
    command = f"python3 {os.path.join(BASE_DIR, 'run_backup.py')} > /var/log/lite-cpanel-backup.log 2>&1"
    
    for line in lines:
        # Filter out old backup jobs
        if 'run_backup.py' not in line:
            new_lines.append(line)
            
    if schedule:
        new_lines.append(f"{schedule} {command}")
        
    write_raw_crontab(new_lines)

def trigger_manual_backup():
    """Start the backup script in the background."""
    script_path = os.path.join(BASE_DIR, 'run_backup.py')
    if not os.path.exists(BACKUP_DIR):
        os.makedirs(BACKUP_DIR, exist_ok=True)
        
    try:
        # Run in background and pipe output to a log file
        log_file = open('/var/log/lite-cpanel-backup.log', 'w')
        subprocess.Popen(['python3', script_path, '--manual'], stdout=log_file, stderr=subprocess.STDOUT)
        return True, "Backup started in the background. Check /var/log/lite-cpanel-backup.log for details."
    except Exception as e:
        return False, f"Failed to start backup: {str(e)}"

def get_local_backups():
    """Returns a list of backups in the /backup directory."""
    if not os.path.exists(BACKUP_DIR):
        return []
        
    backups = []
    for f in os.listdir(BACKUP_DIR):
        if f.endswith('.tar.gz') and f.startswith('lite-cpanel-backup-'):
            filepath = os.path.join(BACKUP_DIR, f)
            stat = os.stat(filepath)
            backups.append({
                'filename': f,
                'path': filepath,
                'size_mb': round(stat.st_size / (1024 * 1024), 2),
                'date': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
            })
            
    # Sort newest first
    backups.sort(key=lambda x: x['date'], reverse=True)
    return backups

def delete_local_backup(filename):
    """Deletes a local backup file safely."""
    # Prevent directory traversal
    safe_filename = os.path.basename(filename)
    filepath = os.path.join(BACKUP_DIR, safe_filename)
    
    if os.path.exists(filepath):
        try:
            os.remove(filepath)
            return True, f"Backup {safe_filename} deleted."
        except Exception as e:
            return False, f"Error deleting backup: {str(e)}"
    return False, "Backup not found."
