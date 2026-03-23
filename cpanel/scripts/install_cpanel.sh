#!/bin/bash

# Ensure root
if [ "$(id -u)" -ne 0 ]; then
  echo "Please run as root"
  exit 1
fi

echo "======================================"
echo "    Installing Python cPanel Stack    "
echo "======================================"

# Install system dependencies
apt-get update
apt-get install -y python3-venv python3-pip libmysqlclient-dev pkg-config

# Get absolute path of the directory
# This handles the case where the script is executed with `sh` or `dash` instead of `bash`
SCRIPT_PATH=$(readlink -f "$0")
SCRIPT_DIR=$(dirname "$SCRIPT_PATH")
CPANEL_DIR=$(dirname "$SCRIPT_DIR")

echo "cPanel Directory: $CPANEL_DIR"

# Setup Python Virtual Environment
echo "Setting up Python virtual environment..."
python3 -m venv $CPANEL_DIR/venv

# Use the virtual environment's pip directly, which avoids the externally-managed-environment error
# and works without needing the `source` command which can fail in `sh`.
echo "Installing Python dependencies..."
$CPANEL_DIR/venv/bin/pip install -r $CPANEL_DIR/requirements.txt

# Generate a permanent secret key for Flask sessions
echo "Generating secure Flask secret key..."
SECRET_KEY=$($CPANEL_DIR/venv/bin/python3 -c "import secrets; print(secrets.token_hex(32))")
cat << EOF > $CPANEL_DIR/app/.env
FLASK_SECRET_KEY=$SECRET_KEY
EOF
chmod 600 $CPANEL_DIR/app/.env

# Create systemd service
echo "Creating systemd service..."
cat << SYSTEMD > /etc/systemd/system/cpanel.service
[Unit]
Description=Gunicorn instance to serve Python cPanel
After=network.target

[Service]
User=root
Group=root
WorkingDirectory=$CPANEL_DIR/app
Environment="PATH=$CPANEL_DIR/venv/bin"
ExecStart=$CPANEL_DIR/venv/bin/gunicorn --workers 3 --bind 0.0.0.0:2083 cpanel:app

[Install]
WantedBy=multi-user.target
SYSTEMD

# Start and enable the service
systemctl daemon-reload
systemctl enable cpanel
systemctl restart cpanel

echo "======================================"
echo "cPanel installed and running on port 2083"
echo "Access it via: http://<your-server-ip>:2083"
echo "Log in using your system root credentials."
echo "======================================"
