<p align="center">
  <img src="cpanel/app/static/logo.png" alt="Lite cPanel Logo" width="260">
</p>

<h1 align="center">Lite cPanel</h1>

<p align="center">
  A lightweight, open-source web hosting control panel for Linux servers.<br>
  Install a full LAMP/LEMP stack and manage your server from a clean, modern web interface.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?logo=python" />
  <img src="https://img.shields.io/badge/Flask-2.x-lightgrey?logo=flask" />
  <img src="https://img.shields.io/badge/Ubuntu-20.04%2B-orange?logo=ubuntu" />
  <img src="https://img.shields.io/badge/License-GPL--3.0-green" />
  <img src="https://img.shields.io/badge/Status-Active-brightgreen" />
</p>

---

## Screenshot

![Lite cPanel Dashboard](screenshot.png)

---

## What is Lite cPanel?

**Lite cPanel** is a self-hosted, open-source server management panel built on Python (Flask). It is designed for developers and system administrators who need a simple, fast, and dependency-light alternative to heavy commercial control panels like cPanel/WHM or Plesk.

It bundles a full automated LAMP/LEMP stack installer alongside a browser-based management interface — all in a single deployable unit.

---

## Features

### 🖥️ Dashboard
- Real-time **CPU, RAM, and Disk** usage meters
- **Live Process View** — auto-refreshing top-10 process table with CPU/Memory percentages and 1/5/15-min load averages
- **System Services Monitor** — live status badges (Active / Inactive / Failed / Uninstalled) for Apache, Nginx, PHP-FPM, MySQL, CSF Firewall, ModSecurity, and Lite cPanel itself
- One-click **Restart** button for each service directly from the dashboard

### 🌐 Domain Manager
- Add and remove Apache/Nginx virtual hosts with a single click
- Enable/Disable individual domains without deleting them
- **SSL Certificate management** — generate and renew Let's Encrypt certificates per domain
- Per-domain **log viewer** with live tail (Apache Error, Apache Access, Nginx Error, Nginx Access, Syslog)

### 🗄️ Database Manager
- Create MySQL/MariaDB databases with a dedicated user and strong password
- **Safe delete** — automatically removes the associated MySQL user when a database is deleted (or revokes only the specific grants if the user is shared)
- Change database user passwords from the panel
- Toggle user host access between `localhost` (local-only) and `%` (remote access)
- One-click **phpMyAdmin login** via secure single-sign-on token bridge

### 📁 FTP Manager
- Create and delete Pure-FTPd virtual FTP users
- Change FTP user passwords
- Bind FTP users to specific web root directories with path traversal prevention

### 🛡️ Firewall (CSF)
- Start, Stop, and Restart ConfigServer Security & Firewall (CSF)
- Allow/Deny IP addresses with a single click
- View and manage temporary allow/deny entries
- Edit the raw `csf.allow`, `csf.deny`, `csf.ignore`, and `csf.conf` files in-browser
- Live port overview

### 🔒 ModSecurity (WAF)
- **One-click installer** — installs `libapache2-mod-security2` + OWASP Core Rule Set directly from the panel with a live progress bar
- Switch between **On / Detection-Only / Off** rule engine modes globally
- Toggle ModSecurity per-domain
- Activate rule profiles (OWASP CRS, Comodo WAF, Custom Rules)
- Edit main config, custom rules, and disabled rules list in-browser
- Live audit log viewer with domain filtering

### 🌟 WordPress Manager
- Auto-install WordPress on any configured domain with an optional sub-path
- Live streaming **progress bar** during installation
- Creates a secure, isolated MySQL database and user — credentials stored **only** in `wp-config.php`
- Detect existing and partial/broken WordPress installations
- One-click **Uninstall** — drops the WordPress database/user and removes all WordPress-specific files

### ⚙️ Settings
- Edit core system configuration files (Apache, Nginx, MariaDB, PHP, FTP) directly in-browser with auto-reload on save
- **System Log Viewer** — tabbed viewer for Apache Error/Access, Nginx Error/Access, Syslog, and MySQL Error logs with auto-scroll and one-click refresh

### 🔐 Security
- System-user authentication (PAM-based — uses the server's existing Linux user accounts)
- CSRF protection on all forms (Flask-WTF)
- Session-based login with configurable secret key
- phpMyAdmin SSO via secure time-limited token files (`/var/lib/cpanel_tokens/`)
- Credential-free panel — database passwords for web apps are stored only inside `wp-config.php`, never in shared password files

---

## Supported Operating Systems

| OS | Version | Status |
|---|---|---|
| **Ubuntu** | 20.04 LTS (Focal) | ✅ Fully Supported |
| **Ubuntu** | 22.04 LTS (Jammy) | ✅ Fully Supported |
| **Ubuntu** | 24.04 LTS (Noble) | ✅ Fully Supported |
| **Debian** | 11 (Bullseye) | ⚠️ Mostly Compatible |
| **Debian** | 12 (Bookworm) | ⚠️ Mostly Compatible |
| Other Linux | Any | ❌ Not Tested |

> **Note:** The automated stack installer (`install.sh`) is written specifically for Ubuntu/Debian `apt`-based systems. The panel itself (Flask app) will run on any Linux distribution with Python 3.10+.

---

## Stack Options

The automated installer supports three web stack configurations:

| Stack | Web Server | PHP | Use Case |
|---|---|---|---|
| **LAMP** | Apache 2 | `mod_php` | Classic shared hosting setup |
| **LEMP** | Nginx | PHP-FPM | High-performance modern sites |
| **Hybrid** | Nginx (port 80) + Apache (port 8080) | PHP-FPM | Best of both — Nginx as proxy, Apache for `.htaccess` compatibility |

All stacks include **MariaDB**, **phpMyAdmin**, and optional **MongoDB**.

---

## Installation

### Requirements
- Ubuntu 20.04+ or Debian 11+
- Root or `sudo` access
- Internet connection
- Git

### Step 1 — Clone the repository

```bash
git clone https://github.com/tysonchamp/Lite-cPanel.git
cd Lite-cPanel
```

### Step 2 — Run the stack installer

```bash
sudo bash install.sh
```

The installer will:
1. Prompt you to choose your preferred web stack (LAMP / LEMP / Hybrid)
2. Install all required packages non-interactively
3. Configure Apache and/or Nginx with a default virtual host
4. Set up MariaDB with a secure root password
5. Install phpMyAdmin with auto-generated credentials
6. Deploy and start the Lite cPanel panel as a system service on port **2083**

### Step 3 — Access the panel

Open your browser and navigate to:

```
http://<your-server-ip>:2083
```

Log in with any **Linux system user** account on that server (e.g. your SSH username/password).

---

## Manual Panel Setup (without the stack installer)

If you already have a web stack and just want the panel:

```bash
cd cpanel
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Set a persistent secret key (recommended)
echo "FLASK_SECRET_KEY=$(openssl rand -hex 32)" > app/.env

# Run with Gunicorn (production)
gunicorn --workers 3 --bind 0.0.0.0:2083 app.cpanel:app

# Or for development only
python3 app/cpanel.py
```

---

## Project Structure

```
Lite-cPanel/
├── install.sh                  # Main orchestrator installer
├── scripts/
│   └── lamp-installer.sh      # Core LAMP/LEMP/Hybrid stack installer
├── cpanel/
│   ├── requirements.txt
│   └── app/
│       ├── cpanel.py           # Flask application & routing
│       ├── auth.py             # PAM authentication
│       ├── database_mgr.py     # MySQL management
│       ├── domains_mgr.py      # Virtual host management
│       ├── ftp_mgr.py          # Pure-FTPd user management
│       ├── modsec_mgr.py       # ModSecurity management & installer
│       ├── security_mgr.py     # CSF Firewall management
│       ├── settings_mgr.py     # Config editor & log viewer
│       ├── wordpress_mgr.py    # WordPress installer & manager
│       ├── static/
│       │   ├── logo.png        # Lite cPanel logo
│       │   └── favicon.png     # Browser favicon
│       └── templates/          # Jinja2 HTML templates
├── screenshot.png
└── README.md
```

---

## Contributing

Contributions are welcome! This project is fully open-source under the GPL-3.0 License.

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Commit your changes: `git commit -m "feat: add my feature"`
4. Push to your branch: `git push origin feature/my-feature`
5. Open a Pull Request

Please follow [Conventional Commits](https://www.conventionalcommits.org/) for commit messages.

---

## Roadmap

- [ ] Email server management (Postfix/Dovecot)
- [ ] Automated backups (scheduled tar/mysqldump with remote upload)
- [ ] Multi-user support with role-based access control
- [ ] Let's Encrypt auto-renewal via cron
- [ ] Docker containerization support
- [ ] Web-based terminal (xterm.js integration)

---

## License

This project is licensed under the **GNU General Public License v3.0**.  
See the [LICENSE](LICENSE) file for full details.

---

## Author

**Tyson Champ**  
📧 tyson.granger181@gmail.com  
🌐 [gbyteinfotech.com](https://www.gbyteinfotech.com)  
🐙 [github.com/tysonchamp](https://github.com/tysonchamp)
