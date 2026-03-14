import subprocess
import os

# ---- CSF Management ----

def check_csf_installed():
    return os.path.exists('/usr/sbin/csf')

def get_csf_status():
    if not check_csf_installed():
        return "Not Installed"

    try:
        # Check if iptables rules for csf exist
        result = subprocess.run(['csf', '-l'], capture_output=True, text=True)
        if "Chain" in result.stdout:
            return "Running"
        return "Stopped"
    except Exception:
        return "Unknown"

def csf_action(action):
    if not check_csf_installed():
        return False, "CSF not installed"

    cmds = {
        'start': ['csf', '-s'],
        'stop': ['csf', '-f'],
        'restart': ['csf', '-r']
    }

    if action in cmds:
        try:
            subprocess.run(cmds[action], check=True, capture_output=True)
            return True, f"CSF {action}ed successfully."
        except subprocess.CalledProcessError as e:
            return False, f"Failed to {action} CSF: {e.stderr.decode()}"
    return False, "Invalid action"

def csf_ip_action(action, ip):
    if not check_csf_installed():
        return False, "CSF not installed"

    cmds = {
        'allow': ['csf', '-a', ip],
        'deny': ['csf', '-d', ip],
        'unallow': ['csf', '-ar', ip],
        'undeny': ['csf', '-dr', ip]
    }

    if action in cmds:
        try:
            result = subprocess.run(cmds[action], check=True, capture_output=True, text=True)
            return True, result.stdout
        except subprocess.CalledProcessError as e:
            return False, f"Action failed: {e.stderr}"
    return False, "Invalid IP action"

def get_csf_file(file_type):
    files = {
        'allow': '/etc/csf/csf.allow',
        'deny': '/etc/csf/csf.deny',
        'config': '/etc/csf/csf.conf'
    }

    path = files.get(file_type)
    if path and os.path.exists(path):
        with open(path, 'r') as f:
            return f.read()
    return ""

def save_csf_file(file_type, content):
    files = {
        'allow': '/etc/csf/csf.allow',
        'deny': '/etc/csf/csf.deny',
        'config': '/etc/csf/csf.conf'
    }

    path = files.get(file_type)
    if path and os.path.exists(path):
        try:
            with open(path, 'w') as f:
                f.write(content)
            # Restart CSF to apply changes
            subprocess.run(['csf', '-r'], check=True, capture_output=True)
            return True, f"Saved {file_type} and restarted CSF."
        except Exception as e:
            return False, str(e)
    return False, "Invalid file"


# ---- ModSecurity Management ----

def check_modsec_installed():
    return os.path.exists('/etc/modsecurity/modsecurity.conf')

def get_modsec_status():
    if not check_modsec_installed():
        return "Not Installed"

    with open('/etc/modsecurity/modsecurity.conf', 'r') as f:
        content = f.read()
        if 'SecRuleEngine On' in content:
            return "On"
        elif 'SecRuleEngine DetectionOnly' in content:
            return "DetectionOnly"
        else:
            return "Off"

def set_modsec_status(status):
    if not check_modsec_installed():
        return False, "ModSecurity not installed."

    valid_statuses = ['On', 'Off', 'DetectionOnly']
    if status not in valid_statuses:
        return False, "Invalid status."

    try:
        path = '/etc/modsecurity/modsecurity.conf'
        with open(path, 'r') as f:
            lines = f.readlines()

        with open(path, 'w') as f:
            for line in lines:
                if line.startswith('SecRuleEngine'):
                    f.write(f'SecRuleEngine {status}\n')
                else:
                    f.write(line)

        # Restart web server (try both)
        subprocess.run(['systemctl', 'reload', 'apache2'], capture_output=True)
        subprocess.run(['systemctl', 'reload', 'nginx'], capture_output=True)
        return True, f"ModSecurity set to {status}."
    except Exception as e:
        return False, str(e)

def get_modsec_audit_log():
    log_path = '/var/log/modsec_audit.log'
    if os.path.exists(log_path):
        try:
            # Get last 50 lines
            result = subprocess.run(['tail', '-n', '50', log_path], capture_output=True, text=True)
            return result.stdout
        except Exception:
            return "Could not read log file."
    return "Log file not found."
