#!/bin/bash

if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (use sudo)"
    exit 1
fi

echo "Setting up phpMyAdmin Signon..."

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
        // Read the file content which contains the password securely
        $db_password = trim(file_get_contents($token_file));

        // Log them in
        $_SESSION['PMA_single_signon_user'] = 'root';
        $_SESSION['PMA_single_signon_password'] = $db_password;

        // Invalidate token immediately
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
