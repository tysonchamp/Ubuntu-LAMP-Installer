# Ubuntu LAMP Stack Installer v2.0

## Enhanced Features
- **Automated Installation**: No user interaction required for MariaDB and phpMyAdmin
- **Strong Password Generation**: Automatically generates secure passwords
- **Multiple Virtual Hosts**: Create unlimited virtual hosts after initial setup
- **Interactive Menu**: Easy-to-use menu system
- **SSL Support**: Built-in Let's Encrypt integration
- **Password Management**: Securely stores generated passwords

## What's Installed
- Apache2 Web Server
- PHP 8.x with essential modules
- MariaDB Server (with secure setup)
- phpMyAdmin (fully configured)
- MongoDB
- OpenSSL & Let's Encrypt
- Webmin Control Panel (optional)

## Quick Start

### First Time Installation
```bash
sudo ./lamp-installer.sh
```
Then select option 1 to install the complete LAMP stack.

### Add Virtual Host (after installation)
```bash
sudo ./lamp-installer.sh example.com
```

### Interactive Mode
```bash
sudo ./lamp-installer.sh
```

## Menu Options
1. **Install LAMP Stack** - Complete automated installation
2. **Add Virtual Host** - Create new website
3. **List Virtual Hosts** - Show all configured sites
4. **Install Webmin** - Add control panel
5. **Setup SSL Certificate** - Configure Let's Encrypt SSL
6. **Show Passwords** - Display generated passwords
7. **Exit**

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
- `lamp-installer.sh` - Main installer script
- `vhost-manager.sh` - Virtual host management
- `webmin.sh` - Webmin installation helper
- `.passwords` - Generated passwords (created after installation)
- `.lamp_config` - Installation status

## Requirements
- Ubuntu 20.04+ or Debian 11+
- Root/sudo access
- Internet connection

## Contact
- Email: tyson.granger181@gmail.com
- Website: www.tysonchamp.com
- GitHub: https://github.com/tysonchamp/Ubuntu-LAMP-Installer
