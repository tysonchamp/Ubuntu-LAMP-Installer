import subprocess
import os
import logging
import grp
import pwd
import re

def check_pureftpd_installed():
    try:
        subprocess.run(['pure-pw', '--help'], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def get_user_directory(username):
    """
    Robustly retrieves the home directory for an FTP/SFTP user from multiple sources.
    """
    # 1. Try pure-pw show
    if check_pureftpd_installed():
        try:
            show_res = subprocess.run(['pure-pw', 'show', username], capture_output=True, text=True)
            if show_res.returncode == 0:
                # Flexible regex for different versions of pure-pw
                m = re.search(r'(?:Directory|Home directory|Relative home directory)\s*:\s*(.*)', show_res.stdout)
                if m:
                    return m.group(1).strip().replace('/./', '/').rstrip('/')
        except: pass

    # 2. Try pure-pw list
    if check_pureftpd_installed():
        try:
            result = subprocess.run(['pure-pw', 'list'], capture_output=True, text=True)
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if line.strip().startswith(f"{username} "):
                        parts = line.split(maxsplit=1)
                        if len(parts) == 2:
                            return parts[1].strip().replace('/./', '/').rstrip('/')
        except: pass

    # 3. Try direct passwd file parsing
    passwd_files = ['/etc/pure-ftpd/pureftpd.passwd', '/etc/pureftpd.passwd']
    for pf in passwd_files:
        if os.path.exists(pf):
            try:
                with open(pf, 'r') as f:
                    for line in f:
                        if line.startswith(f"{username}:"):
                            parts = line.split(':')
                            if len(parts) >= 6:
                                return parts[5].strip().replace('/./', '/').rstrip('/')
            except: pass

    # 4. Try system user home directory (for SFTP users)
    try:
        user_info = pwd.getpwnam(username)
        rel_home = user_info.pw_dir
        # If it's a relative path (common for our jailed SFTP setup), prepend /var/www
        if not rel_home.startswith('/var/www'):
            return os.path.join('/var/www', rel_home.lstrip('/'))
        return rel_home
    except: pass

    return "/var/www"

def ensure_system_user(username, directory, password=None):
    """
    Ensures a system user exists with the correct directory and group.
    """
    try:
        subprocess.run(['groupadd', '-f', 'lite_sftp'], check=True)
        
        # Determine relative home for jail
        relative_home = directory.replace('/var/www', '')
        if not relative_home: relative_home = "/"
        
        # 1. Try to update existing user
        # We use capture_output=True to handle the check manually
        res = subprocess.run(['usermod', '-d', relative_home, '-s', '/usr/sbin/nologin', '-G', 'lite_sftp', username], capture_output=True, text=True)
        
        if res.returncode == 6: # Status 6 means User Not Found
            # 2. Try to create the user
            res2 = subprocess.run(['useradd', '-d', relative_home, '-s', '/usr/sbin/nologin', '-G', 'lite_sftp', username], capture_output=True, text=True)
            if res2.returncode != 0 and res2.returncode != 9: # 9 means User Already Exists (race condition)
                raise Exception(f"useradd failed (status {res2.returncode}): {res2.stderr}")
        elif res.returncode != 0:
            # Some other error occurred with usermod
            raise Exception(f"usermod failed (status {res.returncode}): {res.stderr}")

        if password:
            try:
                pw_proc = subprocess.Popen(['chpasswd'], stdin=subprocess.PIPE, text=True)
                pw_proc.communicate(input=f"{username}:{password}\n")
                # Locking is non-fatal; we want the user to be created even if lock fails
                subprocess.run(['passwd', '-l', username], capture_output=True)
            except Exception as e:
                logging.error(f"Password setting for {username} had issues: {str(e)}")
            
        return True
    except Exception as e:
        logging.error(f"Failed to ensure system user {username}: {str(e)}")
        raise

def get_ftp_users():
    """
    Returns a list of pure-ftpd virtual users with their status.
    Merges results from pure-pw list, direct file parsing, and system group.
    """
    users_map = {} # username -> directory

    # 1. Source: pure-pw list
    if check_pureftpd_installed():
        try:
            result = subprocess.run(['pure-pw', 'list'], capture_output=True, text=True, check=False)
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if not line.strip():
                        continue
                    # Handle both space and colon separators
                    if ':' in line and not any(line.startswith(p) for p in ['/', './']):
                        parts = line.split(':')
                        if len(parts) >= 6:
                            users_map[parts[0].strip()] = parts[5].strip()
                        elif len(parts) == 2:
                            users_map[parts[0].strip()] = parts[1].strip()
                    else:
                        parts = line.split(maxsplit=1)
                        if len(parts) == 2:
                            users_map[parts[0].strip()] = parts[1].strip()
        except Exception as e:
            logging.debug(f"pure-pw list failed: {str(e)}")

    # 2. Source: Direct file parsing (merge)
    passwd_files = ['/etc/pure-ftpd/pureftpd.passwd', '/etc/pureftpd.passwd']
    for pf in passwd_files:
        if os.path.exists(pf):
            try:
                with open(pf, 'r') as f:
                    for line in f:
                        if line.strip() and ':' in line:
                            parts = line.split(':')
                            if len(parts) >= 6:
                                username = parts[0].strip()
                                directory = parts[5].strip()
                                if username not in users_map:
                                    users_map[username] = directory
            except Exception as e:
                logging.debug(f"Error reading {pf}: {str(e)}")

    # 3. Source: System group 'lite_sftp' (merge)
    try:
        try:
            group_info = grp.getgrnam('lite_sftp')
            sftp_users = group_info.gr_mem
        except KeyError:
            sftp_users = []

        for username in sftp_users:
            if username not in users_map:
                directory = get_user_directory(username)
                if directory:
                    users_map[username] = directory
    except Exception as e:
        logging.debug(f"Error scanning lite_sftp group: {str(e)}")

    # 4. Source: Thorough system user scan for 'lite_sftp' group members
    try:
        # getpwall() is more reliable than grp.getgrnam().gr_mem for all types of group membership
        all_users = pwd.getpwall()
        for u in all_users:
            if u.pw_name not in users_map:
                # Exclude obvious system users unless they are in our group
                if u.pw_uid < 1000 and not u.pw_name.startswith('demo'):
                    # Still check them if they might be ours (e.g. demoftp)
                    if u.pw_shell != '/usr/sbin/nologin':
                        continue
                
                try:
                    # Check group membership via groups command (catches primary and secondary)
                    # We check for the exact group name to avoid partial matches
                    res = subprocess.run(['id', '-Gn', u.pw_name], capture_output=True, text=True)
                    if 'lite_sftp' in res.stdout.split():
                        users_map[u.pw_name] = get_user_directory(u.pw_name)
                except: pass
    except Exception as e:
        logging.debug(f"Thorough scan failed: {str(e)}")

    # Convert map to list and add status
    users = []
    for username, directory in users_map.items():
        # Normalize directory: remove trailing /./ and /
        clean_dir = directory.replace('/./', '/').rstrip('/')
        if not clean_dir:
            clean_dir = "/"
        
        enabled = True
        try:
            lock_res = subprocess.run(['passwd', '-S', username], capture_output=True, text=True)
            if ' L ' in lock_res.stdout or lock_res.returncode != 0:
                enabled = False
        except: 
            enabled = False
        
        users.append({
            'username': username,
            'directory': clean_dir,
            'enabled': enabled
        })

    users.sort(key=lambda x: x['username'])
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
            ensure_system_user(username, directory, password)
        except Exception as system_e:
            return True, f"FTP created, but SFTP bridge failed: {str(system_e)}"
        
        return True, f"FTP user {username} created (Disabled). Toggle to Enable."
    except Exception as e:
        return False, str(e)

def delete_ftp_user(username):
    if not check_pureftpd_installed():
        return False, "pure-ftpd is not installed."
    try:
        # 1. Try to delete from Pure-FTPd
        # We don't use check=True because the user might not exist in Pure-FTPd virtual database
        subprocess.run(['pure-pw', 'userdel', username, '-m'], capture_output=True)
        
        # 2. Try to delete the system user (SFTP Bridge)
        subprocess.run(['userdel', username], capture_output=True)
        
        return True, f"User {username} deleted."
    except Exception as e:
        return False, str(e)

def change_ftp_password(username, new_password):
    if not check_pureftpd_installed():
        return False, "pure-ftpd is not installed."
    try:
        # 1. Try to update Pure-FTPd password
        process = subprocess.Popen(['pure-pw', 'passwd', username, '-m'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        process.communicate(input=f"{new_password}\n{new_password}\n")
        
        # 2. Try to update system password (SFTP Bridge)
        try:
            pw_proc = subprocess.Popen(['chpasswd'], stdin=subprocess.PIPE, text=True)
            pw_proc.communicate(input=f"{username}:{new_password}\n")
        except: pass
        
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
        if not os.path.exists(sshd_path):
            return False, "SSH config not found."
            
        subprocess.run(['groupadd', '-f', 'lite_sftp'], check=True)
            
        with open(sshd_path, 'r') as f:
            lines = f.readlines()
        
        # Clean up existing Lite-cPanel configurations to start fresh
        new_lines = []
        skip = False
        for line in lines:
            if '# Added by Lite-cPanel' in line or 'Match Group lite_sftp' in line:
                skip = True
                continue
            if skip and (line.startswith('Match') or line.startswith('# Subsystem')):
                skip = False
            if skip:
                continue
            
            # Update subsystem line
            if 'Subsystem' in line and 'sftp' in line:
                if enable:
                    new_lines.append('Subsystem sftp internal-sftp\n')
                else:
                    new_lines.append('# Subsystem sftp internal-sftp\n')
                continue
                
            new_lines.append(line)
            
        if enable:
            # Always append at the very bottom
            new_lines.append('\n# Added by Lite-cPanel for Jailed SFTP\n')
            new_lines.append('Match Group lite_sftp\n')
            new_lines.append('    ChrootDirectory /var/www\n')
            new_lines.append('    ForceCommand internal-sftp\n')
            new_lines.append('    AllowTcpForwarding no\n')
            new_lines.append('    X11Forwarding no\n')
            new_lines.append('    PasswordAuthentication yes\n')
            
        with open(sshd_path, 'w') as f:
            f.writelines(new_lines)
            
        subprocess.run(['systemctl', 'restart', 'ssh'], check=True)
        return True, f"SFTP {'enabled (Jailed)' if enable else 'disabled'} successfully."
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
            # Robustly get the directory
            directory = get_user_directory(username)
            ensure_system_user(username, directory)
            
            # THE MAGIC FIX: Add the web server (www-data) to the USER'S group
            # This allows the web server to access the files, but other users stay out.
            subprocess.run(['usermod', '-aG', username, 'www-data'], check=True)
            
            if not os.path.exists(directory):
                os.makedirs(directory, exist_ok=True)

            # Ownership: User owns their folder, group is their PRIVATE group
            # Web server (www-data) is a member of this group.
            subprocess.run(['chown', f'{username}:{username}', directory], check=True)
            subprocess.run(['chmod', '770', directory], check=True)
            subprocess.run(['chmod', 'g+s', directory], check=True)

            # Recursively ensure everything inside is manageable by user and web server
            # We use try/except or || true to prevent find from crashing the whole process if it hits a minor issue
            subprocess.run(f"find {directory} -mindepth 1 -exec chown {username}:{username} {{}} + 2>/dev/null || true", shell=True)
            subprocess.run(f"find {directory} -mindepth 1 -type d -exec chmod 770 {{}} + 2>/dev/null || true", shell=True)
            subprocess.run(f"find {directory} -mindepth 1 -type f -exec chmod 660 {{}} + 2>/dev/null || true", shell=True)
            subprocess.run(f"find {directory} -mindepth 1 -type d -exec chmod g+s {{}} + 2>/dev/null || true", shell=True)
            
            # Ensure the parent (/var/www) is 755 (SSH requirement for jail root)
            subprocess.run(['chown', 'root:root', '/var/www'], check=True)
            subprocess.run(['chmod', '755', '/var/www'], check=True)

            try:
                subprocess.run(['systemctl', 'restart', 'apache2'], check=True)
            except: pass
            
            try:
                subprocess.run(['systemctl', 'restart', 'nginx'], check=True)
            except: pass
            
            # Restart PHP-FPM to pick up new group memberships
            try:
                php_versions = subprocess.run("ls /var/run/php/php*-fpm.sock 2>/dev/null | cut -d- -f1 | rev | cut -d/ -f1 | rev", shell=True, capture_output=True, text=True).stdout.splitlines()
                for v in php_versions:
                    subprocess.run(['systemctl', 'restart', f'{v}-fpm'], check=True)
            except: pass
            
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
