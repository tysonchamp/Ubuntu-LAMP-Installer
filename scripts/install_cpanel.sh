#!/bin/bash

# Ensure root
if [ "$(id -u)" -ne 0 ]; then
  echo "Please run as root"
  exit 1
fi

echo "======================================"
echo "    Installing Python cPanel Stack    "
echo "======================================"

# Install system dependencies & panel prerequisites
apt-get update
apt-get install -y zip unzip curl
apt-get install -y python3-venv python3-pip libmysqlclient-dev pkg-config \
    pure-ftpd libwww-perl sendmail iptables wget tar

# Ensure Pure-FTPd is setup for virtual users
echo "Configuring Pure-FTPd..."
groupadd -g 2001 ftpgroup || true
useradd -u 2001 -s /bin/false -d /bin/null -c "pureftpd user" -g ftpgroup ftpuser || true
echo "yes" > /etc/pure-ftpd/conf/ChrootEveryone
echo "yes" > /etc/pure-ftpd/conf/CreateHomeDir
echo "puredb" > /etc/pure-ftpd/auth/50pure
ln -sf /etc/pure-ftpd/conf/PureDB /etc/pure-ftpd/auth/50pure 2>/dev/null
systemctl restart pure-ftpd

# Install CSF Firewall
echo "Installing CSF Firewall..."
if [ ! -d "/etc/csf" ]; then
    cd /usr/src
    rm -fv csf.tgz
    wget https://download.configserver.dev/csf.tgz
    tar -xzf csf.tgz
    cd csf
    sh install.sh
    # Disable testing mode initially to make it functional (Admin should review later)
    # sed -i 's/TESTING = "1"/TESTING = "0"/' /etc/csf/csf.conf
    csf -r
    cd -
fi

# Install ModSecurity depending on web server installed
echo "Installing ModSecurity..."
if [ -x "$(command -v apache2)" ]; then
    apt-get install -y libapache2-mod-security2
    a2enmod security2 || true
    systemctl restart apache2 || true
fi
if [ -x "$(command -v nginx)" ]; then
    apt-get install -y libnginx-mod-http-modsecurity
    systemctl restart nginx || true
fi
# Copy recommended modsecurity config if it doesn't exist
if [ ! -f /etc/modsecurity/modsecurity.conf ] && [ -f /etc/modsecurity/modsecurity.conf-recommended ]; then
    cp /etc/modsecurity/modsecurity.conf-recommended /etc/modsecurity/modsecurity.conf
fi


# Install Node.js
install_nodejs() {
    echo -e "${GREEN}Installing Node.js via NVM...${NC}"
    export NVM_DIR="$HOME/.nvm"
    
    # Ensure NVM is installed
    if [ ! -s "$NVM_DIR/nvm.sh" ]; then
        curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.4/install.sh | bash
    fi
    
    \\. "$NVM_DIR/nvm.sh"
    
    # Ensure Node 24 is installed
    if [[ ! "$(node -v 2>/dev/null)" == v24* ]]; then
        nvm install 24
    fi
    nvm use 24
}
# Install Node.js
install_nodejs


# Get absolute path of the directory
# This handles the case where the script is executed with `sh` or `dash` instead of `bash`
SCRIPT_PATH=$(readlink -f "$0")
SCRIPT_DIR=$(dirname "$SCRIPT_PATH")
PROJECT_ROOT=$(dirname "$SCRIPT_DIR")
CPANEL_DIR="$PROJECT_ROOT/cpanel"

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
ExecStart=$CPANEL_DIR/venv/bin/gunicorn --worker-class gthread --threads 10 --timeout 3600 --workers 3 --bind 0.0.0.0:2083 cpanel:app

[Install]
WantedBy=multi-user.target
SYSTEMD

# Start and enable the service
systemctl daemon-reload
systemctl enable cpanel
systemctl restart cpanel

# Cleanup any previous phpMyAdmin Signon auto-login
echo "Cleaning up phpMyAdmin auto login..."
cd $CPANEL_DIR/app
$CPANEL_DIR/venv/bin/python3 -c "import sys; sys.path.append('$CPANEL_DIR/app'); from database_mgr import setup_phpmyadmin_signon; setup_phpmyadmin_signon()"

# Get MySQL root password for display
MYSQL_ROOT_PASS=$(grep "MySQL Root Password:" /var/lib/lite-cpanel/.passwords | cut -d: -f2- | sed 's/^ *//')

echo "======================================"
echo "cPanel installed and running on port 2083"
echo "Access it via: http://<your-server-ip>:2083"
echo "Log in using your system root credentials."
echo ""
echo "MySQL Root Password: $MYSQL_ROOT_PASS"
echo "======================================"
