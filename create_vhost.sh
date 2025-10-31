#!/bin/bash
#
# Create a new virtual host
#
read -p "Enter the domain name: " domain
read -p "Create a reverse proxy? (y/n): " proxy_choice

if [ "$proxy_choice" == "y" ]; then
    read -p "Enter the proxy port: " proxy_port
fi

# Create the vhost configuration file
cat > /etc/apache2/sites-available/$domain.conf <<EOF
<VirtualHost *:80>
    ServerName $domain
    ServerAlias www.$domain
    DocumentRoot /var/www/$domain
    <Directory /var/www/$domain>
        Options Indexes FollowSymLinks MultiViews
        AllowOverride All
        Order allow,deny
        allow from all
    </Directory>
    ErrorLog \${APACHE_LOG_DIR}/error.log
    CustomLog \${APACHE_LOG_DIR}/access.log combined
</VirtualHost>
EOF

# Create the SSL vhost configuration file
mkdir -p /etc/apache2/ssl
openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout /etc/apache2/ssl/$domain.key -out /etc/apache2/ssl/$domain.crt -subj "/C=US/ST=Denial/L=Springfield/O=Dis/CN=$domain"
cat > /etc/apache2/sites-available/$domain-ssl.conf <<EOF
<IfModule mod_ssl.c>
    <VirtualHost _default_:443>
        ServerName $domain
        ServerAlias www.$domain
        DocumentRoot /var/www/$domain
        <Directory /var/www/$domain>
            Options Indexes FollowSymLinks MultiViews
            AllowOverride All
            Order allow,deny
            allow from all
        </Directory>
        ErrorLog \${APACHE_LOG_DIR}/error.log
        CustomLog \${APACHE_LOG_DIR}/access.log combined
        SSLEngine on
        SSLCertificateFile /etc/apache2/ssl/$domain.crt
        SSLCertificateKeyFile /etc/apache2/ssl/$domain.key
    </VirtualHost>
</IfModule>
EOF

if [ "$proxy_choice" == "y" ]; then
    # Enable proxy modules
    a2enmod proxy proxy_http
    # Add the proxy configuration to both vhost files
    sed -i "/<\/VirtualHost>/i \    ProxyPreserveHost On\n    ProxyRequests Off\n    ProxyPass / http://localhost:$proxy_port/\n    ProxyPassReverse / http://localhost:$proxy_port/" /etc/apache2/sites-available/$domain.conf
    sed -i "/<\/VirtualHost>/i \    ProxyPreserveHost On\n    ProxyRequests Off\n    ProxyPass / http://localhost:$proxy_port/\n    ProxyPassReverse / http://localhost:$proxy_port/" /etc/apache2/sites-available/$domain-ssl.conf
fi

# Create the document root
mkdir -p /var/www/$domain
chown -R www-data:www-data /var/www/$domain
chmod -R 755 /var/www/$domain

# Enable the new vhost
a2ensite $domain.conf
a2ensite $domain-ssl.conf

# Restart Apache
service apache2 restart
