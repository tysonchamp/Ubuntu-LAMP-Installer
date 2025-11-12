# Web Stack Installer v2.0

## Enhanced Features
- **Multiple Web Server Options**: Apache, NGINX, or NGINX+Apache+PHP-FPM
- **Automated Installation**: No user interaction required for MariaDB and phpMyAdmin
- **Strong Password Generation**: Automatically generates secure passwords
- **Multiple Virtual Hosts**: Create unlimited virtual hosts after initial setup
- **Interactive Menu**: Easy-to-use menu system
- **SSL Support**: Built-in Let's Encrypt integration
- **Password Management**: Securely stores generated passwords

## Stack Options

### 1. Apache LAMP Stack
- Apache2 Web Server
- PHP 8.x with mod_php
- MariaDB Server
- phpMyAdmin
- MongoDB

### 2. NGINX Stack
- NGINX Web Server
- PHP 8.x with PHP-FPM
- MariaDB Server
- phpMyAdmin
- MongoDB

### 3. NGINX + Apache + PHP-FPM (Hybrid)
- NGINX as reverse proxy (port 80)
- Apache as backend (port 8080)
- PHP 8.x with PHP-FPM
- MariaDB Server
- phpMyAdmin
- MongoDB

## Quick Start

### First Time Installation
```bash
sudo ./web-stack-installer.sh
```
Then select your preferred stack option.

### Add Virtual Host (after installation)
```bash
sudo ./web-stack-installer.sh example.com
```

### Interactive Mode
```bash
sudo ./web-stack-installer.sh
```

## Menu Options

### First Time Setup
1. **Install Apache LAMP Stack** - Traditional LAMP setup
2. **Install NGINX Stack** - Modern NGINX with PHP-FPM
3. **Install NGINX + Apache + PHP-FPM** - Hybrid configuration
4. **Exit**

### After Installation
1. **Add Virtual Host** - Create new website
2. **List Virtual Hosts** - Show all configured sites
3. **Install Webmin** - Add control panel
4. **Setup SSL Certificate** - Configure Let's Encrypt SSL
5. **Show Passwords** - Display generated passwords
6. **Exit**

## Advanced Virtual Host Management
```bash
# Create SSL-enabled virtual host
sudo ./vhost-manager.sh create-ssl example.com

# Remove virtual host
sudo ./vhost-manager.sh remove example.com

# List all virtual hosts with status
sudo ./vhost-manager.sh list
```

## Security Features
- Auto-generated strong passwords (25 characters)
- Secure MariaDB installation
- Password file with restricted permissions
- SSL/HTTPS support

## File Structure
- `web-stack-installer.sh` - Main installer script (recommended)
- `lamp-installer.sh` - Legacy Apache-only installer
- `vhost-manager.sh` - Virtual host management for Apache only
- `webmin.sh` - Webmin installation helper
- `.passwords` - Generated passwords (created after installation)
- `.stack_config` - Installation status

## Requirements
- Ubuntu 20.04+ or Debian 11+
- Root/sudo access
- Internet connection

## Contact
- Email: tyson.granger181@gmail.com
- Website: www.gbyteinfotech.com
- GitHub: https://github.com/tysonchamp/Ubuntu-LAMP-Installer
