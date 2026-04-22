import os
import glob
import subprocess

def init_environment():
    """Sets up the environment paths for the application."""
    if os.getuid() == 0:
        os.environ["HOME"] = "/root"
        os.environ["PM2_HOME"] = "/root/.pm2"

    # Explicitly prioritize the user's working Node/PM2 path
    paths = [
        "/root/.nvm/versions/node/v24.15.0/bin",
        "/usr/local/sbin", "/usr/local/bin", "/usr/sbin", "/usr/bin", "/sbin", "/bin"
    ]

    nvm_node_paths = glob.glob(os.path.expanduser("~/.nvm/versions/node/*/bin"))
    if nvm_node_paths:
        nvm_node_paths.sort(reverse=True)
        for p in nvm_node_paths:
            if p not in paths:
                paths.append(p)

    os.environ["PATH"] = ":".join(paths) + ":" + os.environ.get("PATH", "")

    # Auto-Resurrect PM2 processes on startup to ensure persistence
    try:
        from process_mgr import get_pm2_cmd, PM2_HOME
        env = os.environ.copy()
        env["PM2_HOME"] = PM2_HOME
        subprocess.run([get_pm2_cmd(), 'resurrect'], capture_output=True, text=True, env=env)
    except Exception:
        pass

def get_flask_secret_key():
    """Retrieves or generates the Flask secret key."""
    key = os.environ.get('FLASK_SECRET_KEY')
    if not key:
        import logging
        logging.warning("No FLASK_SECRET_KEY set in environment. Using a random key. Sessions will invalidate on restart.")
        key = os.urandom(24)
    return key
