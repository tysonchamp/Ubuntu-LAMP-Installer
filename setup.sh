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

if [ -z $1 ]
	then
		echo "Provide website address without http://www. e.g sh install-setup.sh tysonchamp.com!"
		exit 1
fi

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
apt-get install php5 php5-gd php5-common php5-curl php5-gmp -y && apt-get install mysql-server -y
echo "================================================================"
apt-get install phpmyadmin -y
#echo "Include /etc/phpmyadmin/apache.conf" | cat >> /etc/apache2/apache2.conf
echo "================================================================"
a2enmod rewrite
echo "Setting up Virtual Host Configaration Files"
echo " "
echo "================================================================"
sh httpconf.sh $1
mkdir /var/www/$1
chown -R www-data:www-data /var/www/*
chmod -R 755 /var/www/*
echo "================================================================"
service apache2 restart
echo "================================================================"
echo "Want to install the Self-Sign SSL cirtificate?(yes/no):"
read bol
bol="$(echo ${bol} | tr 'A-Z' 'a-z')"

while [ -z $bol ]
do
	echo "Want to install the Self-Sign SSL cirtificate?(yes/no):"
	read bol
	bol="$(echo ${bol} | tr 'A-Z' 'a-z')"
done

if [ $bol = 'yes' ] || [ $bol = 'y' ]
    then
        echo " "
		echo "Self-Sign SSL Installation Process Starts"
		echo " "
		echo "================================================================"
		a2enmod ssl && service apache2 restart
		echo "================================================================"
		mkdir -p /etc/apache2/ssl
		openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout /etc/apache2/ssl/$1.key -out /etc/apache2/ssl/$1.crt
		echo "================================================================"
		sh httpsconf.sh $1
    else if [ -n "$bol" ] || [ -z "$bol" ]
    	then
    	echo "You skiped the SSL Installation...!!"
    fi
fi

echo "Want to install the Webmin Control Panel?(yes/no):"
read bol
bol="$(echo ${bol} | tr 'A-Z' 'a-z')"

while [ -z $bol ]
do
	echo "Want to install the Webmin Control Panel?(yes/no):"
	read bol
	bol="$(echo ${bol} | tr 'A-Z' 'a-z')"
done

if [ $bol = 'yes' ] || [ $bol = 'y' ]
    then
        echo "Installing Webmin Control Panel and It's Dependencis"
		echo " "
		echo "================================================================"
		sh webmin.sh
    else if [ -n "$bol" ] || [ -z "$bol" ]
    	then
    	echo "You skiped the Webmin Control Panel Installation...!!"
    fi
fi