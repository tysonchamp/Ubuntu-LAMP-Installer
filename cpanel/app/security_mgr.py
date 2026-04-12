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
        'config': '/etc/csf/csf.conf',
        'ignore': '/etc/csf/csf.ignore',
        'pignore': '/etc/csf/csf.pignore',
    }

    path = files.get(file_type)
    if path and os.path.exists(path):
        try:
            with open(path, 'w') as f:
                f.write(content)
            # Restart CSF to apply changes (not for config — needs lfd restart too)
            subprocess.run(['csf', '-r'], check=True, capture_output=True)
            return True, f"Saved {file_type} and restarted CSF."
        except Exception as e:
            return False, str(e)
    return False, "Invalid file or file does not exist."


def get_csf_temp_entries():
    """Returns list of temporary allow/deny entries from `csf -t`."""
    if not check_csf_installed():
        return []
    try:
        result = subprocess.run(['csf', '-t'], capture_output=True, text=True)
        entries = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith('#') or 'Temporary' in line or '---' in line:
                continue
            parts = line.split('|')
            if len(parts) >= 5:
                entries.append({
                    'type':      parts[0].strip(),
                    'ip':        parts[1].strip(),
                    'ports':     parts[2].strip(),
                    'direction': parts[3].strip(),
                    'ttl':       parts[4].strip(),
                    'comment':   parts[5].strip() if len(parts) > 5 else ''
                })
        return entries
    except Exception:
        return []


def get_open_ports():
    """Returns the TCP_IN, TCP_OUT, UDP_IN, UDP_OUT port lists from csf.conf."""
    if not check_csf_installed():
        return {}
    conf_path = '/etc/csf/csf.conf'
    if not os.path.exists(conf_path):
        return {}
    ports = {}
    keys = ['TCP_IN', 'TCP_OUT', 'UDP_IN', 'UDP_OUT']
    try:
        with open(conf_path, 'r') as f:
            for line in f:
                line = line.strip()
                for key in keys:
                    if line.startswith(f'{key} =') or line.startswith(f'{key}='):
                        value = line.split('=', 1)[1].strip().strip('"')
                        ports[key] = [p.strip() for p in value.split(',') if p.strip()]
    except Exception:
        pass
    return ports


def get_csf_conf_settings():
    """Parses csf.conf and returns a list of (key, value, comment) tuples — skipping pure comment lines."""
    conf_path = '/etc/csf/csf.conf'
    if not os.path.exists(conf_path):
        return []
    settings = []
    try:
        with open(conf_path, 'r') as f:
            for line in f:
                stripped = line.strip()
                if not stripped or stripped.startswith('#'):
                    continue
                if '=' in stripped:
                    key, val = stripped.split('=', 1)
                    key = key.strip()
                    val = val.strip().strip('"')
                    # Grab inline comment if present
                    comment = ''
                    if '#' in val:
                        val, comment = val.split('#', 1)
                        val = val.strip().strip('"')
                        comment = comment.strip()
                    settings.append({'key': key, 'value': val, 'comment': comment})
    except Exception:
        pass
    return settings


def save_csf_conf_key(key, value):
    """Update a single key=value in csf.conf and restart CSF."""
    conf_path = '/etc/csf/csf.conf'
    if not os.path.exists(conf_path):
        return False, "csf.conf not found."
    try:
        with open(conf_path, 'r') as f:
            lines = f.readlines()
        updated = False
        with open(conf_path, 'w') as f:
            for line in lines:
                stripped = line.strip()
                if stripped.startswith(f'{key} =') or stripped.startswith(f'{key}='):
                    f.write(f'{key} = "{value}"\n')
                    updated = True
                else:
                    f.write(line)
        if not updated:
            return False, f"Key '{key}' not found in csf.conf."
        subprocess.run(['csf', '-r'], capture_output=True)
        return True, f"Updated {key} and restarted CSF."
    except Exception as e:
        return False, str(e)


