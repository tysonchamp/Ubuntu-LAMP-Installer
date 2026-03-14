#!/bin/bash

# Ensure root
if [ "$EUID" -ne 0 ]; then
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
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
CPANEL_DIR="$(dirname "$SCRIPT_DIR")"

echo "cPanel Directory: $CPANEL_DIR"

# Setup Python Virtual Environment
echo "Setting up Python virtual environment..."
python3 -m venv $CPANEL_DIR/venv
source $CPANEL_DIR/venv/bin/activate

# Install requirements
echo "Installing Python dependencies..."
pip install -r $CPANEL_DIR/requirements.txt

# Generate a permanent secret key for Flask sessions
echo "Generating secure Flask secret key..."
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
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
