import os
import pwd
import spwd
import crypt
from functools import wraps
from flask import session, redirect, url_for, flash, request

def check_system_password(username, password):
    """
    Check if the provided username and password match a local system user (like root).
    Note: The script must run with root privileges to read /etc/shadow.
    """
    try:
        # For development purposes, if running as a non-root user and we just want to test
        # We'll allow a fallback admin/password login or simply check if not root.
        if os.geteuid() != 0:
            if username == 'admin' and password == 'password':
                return True
            return False

        # If running as root, authenticate against system users
        shadow_entry = spwd.getspnam(username)
        hashed_password = shadow_entry.sp_pwdp

        # crypt.crypt generates a hash using the same salt found in the hashed_password
        if crypt.crypt(password, hashed_password) == hashed_password:
            return True
    except KeyError:
        # User not found
        pass
    except PermissionError:
        # Cannot read shadow file
        pass

    return False

import logging
from logging.handlers import RotatingFileHandler

# --- Auth Logging Setup for CSF/LFD ---
auth_logger = logging.getLogger('cpanel_auth')
auth_logger.setLevel(logging.INFO)
try:
    log_handler = RotatingFileHandler('/var/log/cpanel_auth.log', maxBytes=1000000, backupCount=5)
    log_handler.setFormatter(logging.Formatter('%(asctime)s %(message)s', '%b %d %H:%M:%S'))
    auth_logger.addHandler(log_handler)
except Exception:
    pass

def log_auth_failure(username, ip):
    auth_logger.info(f"Failed login attempt for user {username} from {ip}")

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function
