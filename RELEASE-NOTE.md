# Updates:
21.04.2026 (Major UI & Analytics Update)

1. **Slick Modern UI/UX**: Completely redesigned the dashboard and sidebar with a premium midnight-gradient aesthetic, refined typography (Inter), and glassmorphism-inspired cards.
2. **Web Traffic Analytics**: Integrated **GoAccess** for real-time web traffic monitoring. Added a dedicated Traffic Monitor module providing per-domain hits, unique visitors, bandwidth stats, and full interactive HTML reports.
3. **Process Manager Hardening**: Implemented **Automatic PM2 Resurrection** on system boot and hardened NVM environment paths to ensure Node.js/Next.js applications persist across system restarts.
4. **Advanced System Metrics**: Expanded the server information module to display CPU clock frequency, platform details (Architecture/KVM), and full OS Distro names (e.g., AlmaLinux/Ubuntu).
5. **Security Log Parsing**: Enhanced SSH login audit logs with dual-format timestamp parsing (ISO/Syslog) for clean, human-readable security event monitoring.
6. **Terminal UX**: Upgraded the web terminal with a custom minimalist scrollbar and improved container styling for a pro-developer feel.
7. **Infrastructure Refactoring**: Migrated to a centralized `base.html` architecture to improve panel stability and eliminate template-related Internal Server Errors.

21.04.2026 (Initial Release)

1. Implemented a full **Node.js Process Manager** powered by PM2, allowing live monitoring and control of background applications.
2. Updated **Certbot** installation to the official Snap-based method for improved reliability on Ubuntu 22.04 and 24.04.
3. Enhanced **SSL Generation** with smart webserver detection (Apache vs Nginx) and automated DNS verification for subdomains to prevent NXDOMAIN failures.
4. Improved **System Health** dashboard with a persistent log viewer in Settings that ensures core log tabs are always accessible.
5. Added NVM path auto-detection to ensure `npm` and `node` are always available to the panel even when installed via version managers.
6. Established strict **Project Guidelines** to ensure production-ready standards for future developments.


13.04.2026

1. Script has been updated to 3.0. Major changes has been done to support latest Ubuntu LTS versions and latest webmin versions. Also added support for installing certbot for ssl certificates.
2. Added support for interactive menu to choose options during installation.
3. Improved error handling and logging for better troubleshooting.
4. Auto Installation of MariaDB & phpMyAdmin.
5. updated readme and documentation for better clarity.
6. Added multiple stack options including NGINX and hybrid configurations.
7. Added support for installing CSF firewall.
8. Added support for installing ModSecurity firewall.
9. Added support for installing Fail2Ban.
10. Added support for installing UFW firewall.
11. Added support for installing Nginx.
12. Added support for installing PHP.
13. Added support for installing MariaDB.
14. Added support for installing phpMyAdmin.
15. Added support for installing Certbot.
16. Added support for installing Webmin.
17. Added support for installing FTP.
18. Added support for installing SSH.

24.01.2016

1. Script has been updated to 1.0 with some new changes. Now users will have choice on installing webmin control panel and ssl certificates. Also http and https apache file config has been splited into two files for better management.

27.01.2016

1. Script has been updated to 1.1. Some minor changes has been done and permission checking has been added.

13.11.2025

1. Script has been updated to 2.0. Major changes has been done to support latest Ubuntu LTS versions and latest webmin versions. Also added support for installing certbot for ssl certificates.
2. Added support for interactive menu to choose options during installation.
3. Improved error handling and logging for better troubleshooting.
4. Auto Installation of MariaDB & phpMyAdmin.
5. updated readme and documentation for better clarity.
6. Added multiple stack options including NGINX and hybrid configurations.
