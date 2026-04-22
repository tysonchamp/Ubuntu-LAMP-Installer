import subprocess
import os

def check_pureftpd_installed():
    try:
        subprocess.run(['pure-pw', '--help'], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def get_ftp_users():
    """
    Returns a list of pure-ftpd virtual users with their status.
    """
    if not check_pureftpd_installed():
        return None

    users = []
    try:
        result = subprocess.run(['pure-pw', 'list'], capture_output=True, text=True, check=True)
        for line in result.stdout.splitlines():
            if line.strip():
                parts = line.split(maxsplit=1)
                if len(parts) == 2:
                    username = parts[0].strip()
                    directory = parts[1].strip()
                    
                    # Check status via System User Lock (SFTP Bridge)
                    enabled = True
                    try:
                        lock_res = subprocess.run(['passwd', '-S', username], capture_output=True, text=True)
                        if ' L ' in lock_res.stdout or lock_res.returncode != 0:
                            enabled = False
                    except: 
                        enabled = False
                    
                    users.append({
                        'username': username,
                        'directory': directory,
                        'enabled': enabled
                    })
    except subprocess.CalledProcessError:
        pass

    return users

def create_ftp_user(username, password, directory):
    """
    Creates a new pure-ftpd virtual user AND a matching system user for SFTP.
    Starts DISABLED by default.
    """
    if not check_pureftpd_installed():
        return False, "pure-ftpd is not installed."

    try:
        if not directory.startswith('/var/www'):
            return False, "Access denied: FTP directory must be within /var/www"
            
        if not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
            subprocess.run(['chown', '-R', 'www-data:www-data', directory], check=True)

        # 1. Create Virtual User (Disabled via -X 19700101)
        process = subprocess.Popen(
            ['pure-pw', 'useradd', username, '-u', 'www-data', '-g', 'www-data', '-d', directory, '-X', '19700101', '-m'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        stdout, stderr = process.communicate(input=f"{password}\n{password}\n")

        if process.returncode != 0:
            return False, f"Failed to create Virtual User: {stderr}"

        # 2. Create System User (Locked, No Login)
        try:
            subprocess.run(['userdel', '-r', username], capture_output=True)
            subprocess.run(['groupadd', '-f', 'lite_sftp'], check=True)
            subprocess.run(['useradd', '-d', directory, '-s', '/usr/sbin/nologin', '-G', 'lite_sftp', username], check=True)
            
            pw_proc = subprocess.Popen(['chpasswd'], stdin=subprocess.PIPE, text=True)
            pw_proc.communicate(input=f"{username}:{password}\n")
            subprocess.run(['passwd', '-l', username], check=True)
        except Exception as system_e:
            return True, f"FTP created, but SFTP bridge failed: {str(system_e)}"

        return True, f"FTP user {username} created (Disabled). Toggle to Enable."
    except Exception as e:
        return False, str(e)

def delete_ftp_user(username):
    if not check_pureftpd_installed():
        return False, "pure-ftpd is not installed."
    try:
        subprocess.run(['pure-pw', 'userdel', username, '-m'], check=True)
        subprocess.run(['userdel', username], capture_output=True)
        return True, f"User {username} deleted."
    except Exception as e:
        return False, str(e)

def change_ftp_password(username, new_password):
    if not check_pureftpd_installed():
        return False, "pure-ftpd is not installed."
    try:
        process = subprocess.Popen(['pure-pw', 'passwd', username, '-m'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        process.communicate(input=f"{new_password}\n{new_password}\n")
        
        pw_proc = subprocess.Popen(['chpasswd'], stdin=subprocess.PIPE, text=True)
        pw_proc.communicate(input=f"{username}:{new_password}\n")
        return True, f"Password updated for {username}."
    except Exception as e:
        return False, str(e)

def get_sftp_status():
    try:
        if not os.path.exists('/etc/ssh/sshd_config'):
            return False
        with open('/etc/ssh/sshd_config', 'r') as f:
            for line in f:
                if 'Subsystem' in line and 'sftp' in line and 'internal-sftp' in line:
                    return not line.strip().startswith('#')
        return False
    except:
        return False

def toggle_sftp(enable=True):
    try:
        sshd_path = '/etc/ssh/sshd_config'
        subprocess.run(['groupadd', '-f', 'lite_sftp'], check=True)
        with open(sshd_path, 'r') as f:
            lines = f.readlines()
        new_lines = []
        found_sub = False
        in_match = False
        for line in lines:
            if 'Subsystem' in line and 'sftp' in line:
                found_sub = True
                new_lines.append(f"{'' if enable else '# '}Subsystem sftp internal-sftp\n")
                continue
            if 'Match Group lite_sftp' in line:
                in_match = True
                continue
            if in_match:
                if line.startswith('Match') or (line.strip() == '' and not any('Chroot' in next_l for next_l in lines[lines.index(line):lines.index(line)+5])):
                    in_match = False
                else: continue
            new_lines.append(line)
        if not found_sub and enable:
            new_lines.append('Subsystem sftp internal-sftp\n')
        if enable:
            new_lines.append('\nMatch Group lite_sftp\n    ChrootDirectory %h\n    ForceCommand internal-sftp\n    AllowTcpForwarding no\n')
        with open(sshd_path, 'w') as f:
            f.writelines(new_lines)
        subprocess.run(['systemctl', 'restart', 'ssh'], check=True)
        return True, f"SFTP {'enabled (Jailed)' if enable else 'disabled'}."
    except Exception as e:
        return False, str(e)

def toggle_ftp_user_status(username, enable=True):
    try:
        date_val = "0" if enable else "19700101"
        subprocess.run(['pure-pw', 'usermod', username, '-X', date_val, '-m'], check=True)
        user_exists = False
        try:
            subprocess.run(['id', username], check=True, capture_output=True)
            user_exists = True
        except: pass
        if enable:
            show_res = subprocess.run(['pure-pw', 'show', username], capture_output=True, text=True)
            import re
            m = re.search(r'Directory\s*:\s*(.*)', show_res.stdout)
            directory = m.group(1).strip().replace('/./', '/').rstrip('/') if m else "/var/www"
            if not user_exists:
                subprocess.run(['groupadd', '-f', 'lite_sftp'], check=True)
                subprocess.run(['useradd', '-d', directory, '-s', '/usr/sbin/nologin', '-G', 'lite_sftp', username], check=True)
            # Jailing requirements: Root owned parent
            subprocess.run(['chown', 'root:root', directory], check=True)
            subprocess.run(['chmod', '755', directory], check=True)
            try:
                subprocess.run(['passwd', '-u', username], check=True)
            except:
                pw_proc = subprocess.Popen(['chpasswd'], stdin=subprocess.PIPE, text=True)
                pw_proc.communicate(input=f"{username}:SetPasswordInPanel123!\n")
                subprocess.run(['passwd', '-u', username], check=True)
        else:
            if user_exists:
                subprocess.run(['passwd', '-l', username], check=True)
        return True, f"User {username} {'enabled (Jailed)' if enable else 'disabled'}."
    except Exception as e:
        return False, str(e)
