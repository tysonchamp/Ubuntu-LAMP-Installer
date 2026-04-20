#!/bin/bash

if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (use sudo)"
    exit 1
fi

echo "Setting up phpMyAdmin Signon..."

# Get MySQL root password if available
MYSQL_PASS=""
PASS_FILE="/var/lib/lite-cpanel/.passwords"
if [ -f "$PASS_FILE" ]; then
    MYSQL_PASS=$(grep "MySQL Root Password:" "$PASS_FILE" | cut -d: -f2- | sed 's/^ *//')
fi

# Create pma_sso user if not exists
SSO_PASS_FILE="/var/lib/lite-cpanel/.pma_sso_pass"
if [ ! -f "$SSO_PASS_FILE" ]; then
    SSO_PASS=$(openssl rand -base64 16)
    echo "$SSO_PASS" > "$SSO_PASS_FILE"
    chmod 600 "$SSO_PASS_FILE"
    
    # Create user
    SQL="CREATE USER IF NOT EXISTS 'pma_sso'@'localhost' IDENTIFIED BY '$SSO_PASS'; GRANT ALL PRIVILEGES ON *.* TO 'pma_sso'@'localhost' WITH GRANT OPTION; FLUSH PRIVILEGES;"
    if [ -n "$MYSQL_PASS" ]; then
        mysql -u root -p"$MYSQL_PASS" -e "$SQL" 2>/dev/null || echo "Failed to create pma_sso user with password."
    else
        mysql -u root -e "$SQL" 2>/dev/null || echo "Failed to create pma_sso user without password."
    fi
else
    echo "pma_sso password file exists."
fi

# Ensure config directory exists
mkdir -p /etc/phpmyadmin/conf.d

# Write the Signon config overrides
cat > /etc/phpmyadmin/conf.d/cpanel_signon.php << 'EOF'
<?php
$cfg['Servers'][1]['auth_type'] = 'signon';
$cfg['Servers'][1]['SignonSession'] = 'PMA_Signon';
$cfg['Servers'][1]['SignonURL'] = '/phpmyadmin/phpmyadmin_login.php';
$cfg['Servers'][1]['LogoutURL'] = '/';
?>
EOF

# Write the actual login bridge script
cat > /usr/share/phpmyadmin/phpmyadmin_login.php << 'EOF'
<?php
session_name('PMA_Signon');
session_start();

if (isset($_GET['token']) && preg_match('/^[a-f0-9]{32}$/', $_GET['token'])) {
    $token = $_GET['token'];
    $token_file = "/var/lib/cpanel_tokens/pma_{$token}.txt";

    if (file_exists($token_file)) {
        $contents = trim(file_get_contents($token_file));
        // Format: "user:password" — password may be empty
        $parts = explode(':', $contents, 2);
        $db_user = isset($parts[0]) ? $parts[0] : 'root';
        $db_pass = isset($parts[1]) ? $parts[1] : '';

        $_SESSION['PMA_single_signon_user'] = $db_user;
        $_SESSION['PMA_single_signon_password'] = $db_pass;

        unlink($token_file);

        header('Location: /phpmyadmin/index.php');
        die();
    }
}

echo "Invalid or expired login token.";
?>
EOF

# Make sure it is securely readable by the webserver
chmod 644 /usr/share/phpmyadmin/phpmyadmin_login.php

# Create tokens directory for cpanel to use
mkdir -p /var/lib/cpanel_tokens
chown -R www-data:www-data /var/lib/cpanel_tokens
chmod 750 /var/lib/cpanel_tokens

echo "phpMyAdmin Signon configuration completed successfully!"
