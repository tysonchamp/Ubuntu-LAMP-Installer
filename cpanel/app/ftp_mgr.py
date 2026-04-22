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
                    
                    # Check status via show command
                    status = True
                    try:
                        show_res = subprocess.run(['pure-pw', 'show', username], capture_output=True, text=True)
                        if 'Account expiration date' in show_res.stdout:
                            # If there's a date in the past, it's disabled
                            # Usually looks like: Account expiration date : Thu Jan  1 01:00:00 1970
                            if '1970' in show_res.stdout:
                                status = False
                    except: pass
                    
                    users.append({
                        'username': username,
                        'directory': directory,
                        'enabled': status
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

def create_ftp_user(username, password, directory):
    """
    Creates a new pure-ftpd virtual user.
    """
    if not check_pureftpd_installed():
        return False, "pure-ftpd is not installed."

    try:
        # SECURITY: Strictly enforce /var/www boundary for FTP directories
        if not directory.startswith('/var/www'):
            return False, "Access denied: FTP directory must be within /var/www"
            
        # Ensure directory exists
        if not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
            # Safe chown
            subprocess.run(['chown', '-R', 'www-data:www-data', directory], check=True)

        # pure-pw useradd <login> -u <uid> -g <gid> -d <home> -m (updates db)
        # It reads password from stdin
        process = subprocess.Popen(
            ['pure-pw', 'useradd', username, '-u', 'www-data', '-g', 'www-data', '-d', directory, '-m'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        # pure-pw expects password twice
        stdout, stderr = process.communicate(input=f"{password}\n{password}\n")

        if process.returncode == 0:
            return True, f"FTP user {username} created successfully."
        else:
            return False, f"Failed to create FTP user: {stderr}"

    except Exception as e:
        return False, str(e)

def delete_ftp_user(username):
    """
    Deletes a pure-ftpd virtual user.
    """
    if not check_pureftpd_installed():
        return False, "pure-ftpd is not installed."

    try:
        # pure-pw userdel <login> -m (updates db)
        result = subprocess.run(
            ['pure-pw', 'userdel', username, '-m'],
            capture_output=True,
            text=True,
            check=True
        )
        return True, f"FTP user {username} deleted successfully."
    except subprocess.CalledProcessError as e:
        return False, f"Failed to delete FTP user: {e.stderr}"

def change_ftp_password(username, new_password):
    """
    Changes the password of a pure-ftpd virtual user.
    """
    if not check_pureftpd_installed():
        return False, "pure-ftpd is not installed."

    try:
        process = subprocess.Popen(
            ['pure-pw', 'passwd', username, '-m'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        stdout, stderr = process.communicate(input=f"{new_password}\n{new_password}\n")

        if process.returncode == 0:
            return True, f"Password changed for FTP user {username}."
        else:
            return False, f"Failed to change password: {stderr}"

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
