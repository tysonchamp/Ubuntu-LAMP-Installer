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
                        # Check if system user is locked or doesn't exist
                        lock_res = subprocess.run(['passwd', '-S', username], capture_output=True, text=True)
                        if ' L ' in lock_res.stdout or lock_res.returncode != 0:
                            # 'L' means Locked, returncode != 0 means user doesn't exist
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

def toggle_ftp_user_status(username, enable=True):
    """
    Enables or disables an FTP user by setting an expiration date.
    """
    if not check_pureftpd_installed():
        return False, "pure-ftpd is not installed."

    try:
        # -X 0 = No expiration (Enabled)
        # -X 19700101 = Expired (Disabled)
        date_val = "0" if enable else "19700101"
        subprocess.run(['pure-pw', 'usermod', username, '-X', date_val, '-m'], check=True)
        return True, f"FTP user {username} {'enabled' if enable else 'disabled'} successfully."
    except Exception as e:
        return False, str(e)

def toggle_ftp_user_status(username, enable=True):
    """
    Enables or disables an FTP user by setting an expiration date 
    AND manages a matching system user for SFTP access.
    """
    if not check_pureftpd_installed():
        return False, "pure-ftpd is not installed."

    try:
        # 1. Manage Pure-FTPd (Virtual User)
        date_val = "0" if enable else "19700101"
        subprocess.run(['pure-pw', 'usermod', username, '-X', date_val, '-m'], check=True)
        
        # 2. Manage System User (SFTP Bridge)
        # Check if user exists in /etc/passwd
        user_exists = False
        try:
            subprocess.run(['id', username], check=True, capture_output=True)
            user_exists = True
        except: pass

        if enable:
            if not user_exists:
                # Create system user for SFTP
                show_res = subprocess.run(['pure-pw', 'show', username], capture_output=True, text=True)
                import re
                m = re.search(r'Directory\s*:\s*(.*)', show_res.stdout)
                # Clean path: remove trailing /./ and /
                directory = m.group(1).strip() if m else "/var/www"
                directory = directory.replace('/./', '/').rstrip('/')
                
                # Create with no login shell
                subprocess.run(['useradd', '-d', directory, '-s', '/usr/sbin/nologin', username], check=True)
                # Set a dummy password initially so it can be unlocked
                pw_proc = subprocess.Popen(['chpasswd'], stdin=subprocess.PIPE, text=True)
                pw_proc.communicate(input=f"{username}:SetPasswordInPanel123!\n")
            
            # Unlock the account
            try:
                subprocess.run(['passwd', '-u', username], check=True)
            except:
                # If unlock fails, try setting a password first
                pw_proc = subprocess.Popen(['chpasswd'], stdin=subprocess.PIPE, text=True)
                pw_proc.communicate(input=f"{username}:SetPasswordInPanel123!\n")
                subprocess.run(['passwd', '-u', username], check=True)
        else:
            if user_exists:
                # Lock the account to disable SFTP
                subprocess.run(['passwd', '-l', username], check=True)

        return True, f"FTP & SFTP access for {username} {'enabled' if enable else 'disabled'} successfully."
    except Exception as e:
        return False, str(e)

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
            # Delete if exists to ensure clean state
            subprocess.run(['userdel', '-r', username], capture_output=True)
            
            # Create user
            subprocess.run(['useradd', '-d', directory, '-s', '/usr/sbin/nologin', username], check=True)
            
            # Set Password
            pw_proc = subprocess.Popen(['chpasswd'], stdin=subprocess.PIPE, text=True)
            pw_proc.communicate(input=f"{username}:{password}\n")
            
            # Immediately Lock (Disabled by default)
            subprocess.run(['passwd', '-l', username], check=True)
        except Exception as system_e:
            return True, f"FTP created, but SFTP bridge failed: {str(system_e)}"

        return True, f"FTP user {username} created (Disabled by default). Toggle to Enable."

    except Exception as e:
        return False, str(e)

def delete_ftp_user(username):
    """
    Deletes a pure-ftpd virtual user and the matching system user.
    """
    if not check_pureftpd_installed():
        return False, "pure-ftpd is not installed."

    try:
        # Delete Virtual
        subprocess.run(['pure-pw', 'userdel', username, '-m'], check=True)
        
        # Delete System
        try:
            subprocess.run(['userdel', username], capture_output=True)
        except: pass
        
        return True, f"FTP/SFTP user {username} deleted successfully."
    except subprocess.CalledProcessError as e:
        return False, f"Failed to delete user: {e.stderr}"

def change_ftp_password(username, new_password):
    """
    Changes password for both virtual and system user.
    """
    if not check_pureftpd_installed():
        return False, "pure-ftpd is not installed."

    try:
        # 1. Virtual Password
        process = subprocess.Popen(
            ['pure-pw', 'passwd', username, '-m'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        process.communicate(input=f"{new_password}\n{new_password}\n")

        # 2. System Password
        try:
            pw_proc = subprocess.Popen(['chpasswd'], stdin=subprocess.PIPE, text=True)
            pw_proc.communicate(input=f"{username}:{new_password}\n")
        except: pass

        return True, f"Password updated for {username}."

    except Exception as e:
        return False, str(e)

def get_sftp_status():
    """Checks if SFTP subsystem is enabled in sshd_config."""
    try:
        if not os.path.exists('/etc/ssh/sshd_config'):
            return False
        with open('/etc/ssh/sshd_config', 'r') as f:
            for line in f:
                if 'Subsystem' in line and 'sftp' in line:
                    return not line.strip().startswith('#')
        return False
    except:
        return False

def toggle_sftp(enable=True):
    """Enables or disables SFTP subsystem in sshd_config."""
    try:
        sshd_path = '/etc/ssh/sshd_config'
        if not os.path.exists(sshd_path):
            return False, "SSH config not found."
            
        with open(sshd_path, 'r') as f:
            lines = f.readlines()
        
        new_lines = []
        found = False
        for line in lines:
            if 'Subsystem' in line and 'sftp' in line:
                found = True
                if enable:
                    # Remove comment if present
                    new_lines.append(line.lstrip('# ').strip() + '\n')
                else:
                    # Add comment if not present
                    if not line.strip().startswith('#'):
                        new_lines.append('# ' + line.strip() + '\n')
                    else:
                        new_lines.append(line)
            else:
                new_lines.append(line)
        
        if not found and enable:
            # Try to find a good place to add it or just append
            new_lines.append('\n# Added by Lite-cPanel\nSubsystem sftp /usr/lib/openssh/sftp-server\n')
            
        with open(sshd_path, 'w') as f:
            f.writelines(new_lines)
            
        # Restart SSH to apply
        subprocess.run(['systemctl', 'restart', 'ssh'], check=True)
        return True, f"SFTP {'enabled' if enable else 'disabled'} successfully."
    except Exception as e:
        return False, str(e)
