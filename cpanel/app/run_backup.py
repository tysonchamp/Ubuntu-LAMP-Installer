import os
import sys
import json
import subprocess
import tarfile
import time
import ftplib
import shutil
from datetime import datetime, timedelta

try:
    import boto3
except ImportError:
    boto3 = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, 'backup_config.json')
PASSWORDS_FILE = os.path.abspath(os.path.join(BASE_DIR, '../../scripts/.passwords'))
BACKUP_DIR = '/backup'
TEMP_DIR = '/tmp/lite_cpanel_backups'

def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")
    sys.stdout.flush()

def get_settings():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            log(f"Error reading config: {e}")
    return {}

def get_mysql_password():
    password = ''
    if os.path.exists(PASSWORDS_FILE):
        with open(PASSWORDS_FILE, 'r') as f:
            for line in f:
                if line.startswith('MySQL Root Password:'):
                    password = line.split(':', 1)[1].strip()
                    break
    return password

def cleanup_local_backups(retention_days):
    if not os.path.exists(BACKUP_DIR):
        return
    
    log(f"Cleaning up local backups older than {retention_days} days...")
    cutoff = time.time() - (retention_days * 86400)
    for f in os.listdir(BACKUP_DIR):
        if f.endswith('.tar.gz') and f.startswith('lite-cpanel-backup-'):
            filepath = os.path.join(BACKUP_DIR, f)
            if os.stat(filepath).st_mtime < cutoff:
                try:
                    os.remove(filepath)
                    log(f"Deleted old backup: {f}")
                except Exception as e:
                    log(f"Failed to delete {f}: {e}")

def run_backup():
    settings = get_settings()
    if not settings:
        log("No backup settings found. Exiting.")
        return

    # 1. Setup
    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    backup_filename = f"lite-cpanel-backup-{timestamp}.tar.gz"
    
    if not os.path.exists(TEMP_DIR):
        os.makedirs(TEMP_DIR, exist_ok=True)
        
    temp_sql_file = os.path.join(TEMP_DIR, f"alldbs-{timestamp}.sql")
    temp_tar_file = os.path.join(TEMP_DIR, backup_filename)
    
    # 2. Dump MySQL
    log("Starting MySQL dump...")
    mysql_pass = get_mysql_password()
    dump_cmd = ['mysqldump', '--all-databases']
    if mysql_pass:
        dump_cmd = ['mysqldump', f'-p{mysql_pass}', '--all-databases']
        
    try:
        with open(temp_sql_file, 'w') as sql_out:
            subprocess.run(dump_cmd, stdout=sql_out, stderr=subprocess.PIPE, check=True)
        log("MySQL dump completed successfully.")
    except Exception as e:
        log(f"MySQL dump failed: {e}")
        return

    # 3. Create Tar Archive
    log("Creating compressed tar archive containing /var/www and MySQL dump...")
    try:
        with tarfile.open(temp_tar_file, "w:gz") as tar:
            if os.path.exists('/var/www'):
                tar.add('/var/www', arcname='www')
            tar.add(temp_sql_file, arcname=f"alldbs-{timestamp}.sql")
        log(f"Archive created: {temp_tar_file}")
    except Exception as e:
        log(f"Archive creation failed: {e}")
        return

    # 4. Storage Handling
    if settings.get('local_enabled', True):
        log("Saving to local /backup directory...")
        if not os.path.exists(BACKUP_DIR):
            os.makedirs(BACKUP_DIR, exist_ok=True)
        final_local_path = os.path.join(BACKUP_DIR, backup_filename)
        shutil.copy2(temp_tar_file, final_local_path)
        log(f"Local backup saved at {final_local_path}")
        
        # Cleanup old backups
        retention = int(settings.get('retention_days', 7))
        cleanup_local_backups(retention)

    if settings.get('ftp_enabled', False):
        log("Uploading to FTP server...")
        try:
            host = settings.get('ftp_host')
            port = int(settings.get('ftp_port', 21))
            user = settings.get('ftp_user')
            password = settings.get('ftp_pass')
            remote_path = settings.get('ftp_path', '/')
            
            ftp = ftplib.FTP()
            ftp.connect(host, port)
            ftp.login(user, password)
            ftp.cwd(remote_path)
            
            with open(temp_tar_file, 'rb') as f:
                ftp.storbinary(f'STOR {backup_filename}', f)
                
            ftp.quit()
            log("FTP upload completed successfully.")
        except Exception as e:
            log(f"FTP upload failed: {e}")

    if settings.get('s3_enabled', False):
        log("Uploading to S3 / DigitalOcean Spaces...")
        if not boto3:
            log("Error: boto3 is not installed. Run 'pip install boto3' first.")
        else:
            try:
                endpoint = settings.get('s3_endpoint')
                access_key = settings.get('s3_access_key')
                secret_key = settings.get('s3_secret_key')
                bucket = settings.get('s3_bucket')
                region = settings.get('s3_region')
                
                session = boto3.session.Session()
                client = session.client('s3',
                                        region_name=region,
                                        endpoint_url=endpoint,
                                        aws_access_key_id=access_key,
                                        aws_secret_access_key=secret_key)
                
                client.upload_file(temp_tar_file, bucket, backup_filename)
                log("S3 upload completed successfully.")
            except Exception as e:
                log(f"S3 upload failed: {e}")

    # 5. Final Cleanup
    log("Cleaning up temporary files...")
    try:
        os.remove(temp_sql_file)
        os.remove(temp_tar_file)
    except Exception as e:
        log(f"Cleanup failed: {e}")
        
    log("Backup process finished.")

if __name__ == "__main__":
    run_backup()
