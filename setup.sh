#!/bin/bash
#
# Auto Ubuntu Web Server Setup Script
# 
# Copyright 2014 tysonchamp <tyson.granger181@gmail.com>
# 
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# 
# 
echo "Installing Latest Updates Process starts:"
echo " "
echo "================================================================"
apt-get update && apt-get upgrade -y
echo " "
echo "LAMP Stack with OpenSSL and phpMyAdmin"
echo "Installation Process Starts:"
echo " "
echo "================================================================"
apt-get install openssl -y && apt-get install apache2 -y
echo "================================================================"
apt-get install php5 php5-gd php5-common php5-curl php5-gmp -y && apt-get install mariadb-server -y
# Secure MariaDB installation
password=$(openssl rand -base64 12)
mysql -sfu root <<EOF
-- set root password
ALTER USER 'root'@'localhost' IDENTIFIED BY '$password';
-- remove anonymous users
DELETE FROM mysql.user WHERE User='';
-- disallow remote root login
DELETE FROM mysql.user WHERE User='root' AND Host NOT IN ('localhost', '1227.0.0.1', '::1');
-- remove test database
DROP DATABASE IF EXISTS test;
DELETE FROM mysql.db WHERE Db='test' OR Db='test\\_%';
-- flush privileges
FLUSH PRIVILEGES;
EOF
echo "================================================================"
debconf-set-selections <<< "phpmyadmin phpmyadmin/dbconfig-install boolean true"
debconf-set-selections <<< "phpmyadmin phpmyadmin/app-password-confirm password $password"
debconf-set-selections <<< "phpmyadmin phpmyadmin/mysql/admin-pass password $password"
debconf-set-selections <<< "phpmyadmin phpmyadmin/mysql/app-pass password $password"
debconf-set-selections <<< "phpmyadmin phpmyadmin/reconfigure-webserver multiselect apache2"
apt-get install phpmyadmin -y
#echo "Include /etc/phpmyadmin/apache.conf" | cat >> /etc/apache2/apache2.conf
a2enmod ssl && service apache2 restart
a2enmod rewrite && service apache2 restart
mkdir /var/w/
chown -R www-data:www-data /var/www/*
chmod -R 755 /var/www/*
mkdir -p /etc/apache2/ssl
echo " "
echo "Initial setup complete. Run create_vhost.sh to create a new virtual host."
echo "MariaDB root password stored in /root/.mysql_password"
echo $password > /root/.mysql_password
