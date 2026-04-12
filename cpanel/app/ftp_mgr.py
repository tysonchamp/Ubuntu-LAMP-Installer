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
    Returns a list of pure-ftpd virtual users.
    """
    if not check_pureftpd_installed():
        return None

    users = []
    try:
        # pure-pw list format:
        # username  /path/to/dir
        result = subprocess.run(['pure-pw', 'list'], capture_output=True, text=True, check=True)
        for line in result.stdout.splitlines():
            if line.strip():
                parts = line.split(maxsplit=1)
                if len(parts) == 2:
                    users.append({
                        'username': parts[0].strip(),
                        'directory': parts[1].strip()
                    })
    except subprocess.CalledProcessError:
        pass

    return users

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
