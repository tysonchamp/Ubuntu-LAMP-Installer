import os
import subprocess
import re

MODSEC_CONF_PATH = '/etc/modsecurity/modsecurity.conf'
MODSEC_RULES_DIR = '/etc/modsecurity/rules'
MODSEC_CUSTOM_RULES = '/etc/modsecurity/rules/custom_rules.conf'
MODSEC_DISABLED_RULES = '/etc/modsecurity/rules/disabled_rules.conf'
MODSEC_AUDIT_LOG = '/var/log/modsec_audit.log'

def check_modsec_installed():
    return os.path.exists(MODSEC_CONF_PATH)

def get_modsec_status():
    if not check_modsec_installed():
        return "Not Installed"

    try:
        with open(MODSEC_CONF_PATH, 'r') as f:
            content = f.read()
            if 'SecRuleEngine On' in content:
                return "On"
            elif 'SecRuleEngine DetectionOnly' in content:
                return "DetectionOnly"
            else:
                return "Off"
    except Exception:
        return "Unknown"

def set_modsec_status(status):
    if not check_modsec_installed():
        return False, "ModSecurity not installed."

    valid_statuses = ['On', 'Off', 'DetectionOnly']
    if status not in valid_statuses:
        return False, "Invalid status."

    try:
        with open(MODSEC_CONF_PATH, 'r') as f:
            lines = f.readlines()

        with open(MODSEC_CONF_PATH, 'w') as f:
            for line in lines:
                if line.strip().startswith('SecRuleEngine'):
                    f.write(f'SecRuleEngine {status}\n')
                else:
                    f.write(line)

        # Reload web servers
        subprocess.run(['systemctl', 'reload', 'apache2'], capture_output=True)
        subprocess.run(['systemctl', 'reload', 'nginx'], capture_output=True)
        return True, f"ModSecurity global status set to {status}."
    except Exception as e:
        return False, str(e)

def get_modsec_profiles():
    """
    Returns a list of rule profiles and their enabled status.
    In a real system, this would check which rulesets are included.
    We'll simulate OWASP and Comodo for now.
    """
    profiles = [
        {'id': 'owasp', 'name': 'OWASP Core Rule Set (CRS)', 'description': 'Standard high-security ruleset.'},
        {'id': 'comodo', 'name': 'Comodo WAF', 'description': 'Excellent version with automatic updates.'},
        {'id': 'custom', 'name': 'Custom Rules Only', 'description': 'Only run your own defined rules.'}
    ]
    # For now, let's assume 'owasp' is what people usually have.
    # In a full implementation, this would check include lines in modsecurity.conf or similar.
    return profiles

def get_domains_modsec_status():
    """
    Scans vhost files to see if ModSecurity is explicitly disabled for any domain.
    """
    from domains_mgr import get_virtual_hosts
    vhosts = get_virtual_hosts()
    results = []

    for v in vhosts:
        domain = v['domain']
        status = True # Default to enabled (global status applies)
        
        # Check Apache config
        if 'Apache' in v['servers']:
            path = v['config_paths'].get('Apache')
            if path and os.path.exists(path):
                with open(path, 'r') as f:
                    if 'SecRuleEngine Off' in f.read():
                        status = False

        # Check Nginx config
        if 'Nginx' in v['servers'] and status: # If already False, skip
            path = v['config_paths'].get('Nginx')
            if path and os.path.exists(path):
                with open(path, 'r') as f:
                    content = f.read()
                    if 'modsecurity off;' in content or 'modsecurity_rules_file' not in content:
                        # Depending on how Nginx is set up, missing rules file might mean off
                        if 'modsecurity off;' in content:
                            status = False

        results.append({
            'domain': domain,
            'status': status,
            'servers': v['servers']
        })
    
    return results

def toggle_domain_modsec(domain, enabled):
    """
    Adds or removes SecRuleEngine Off / modsecurity off from vhost files.
    """
    from domains_mgr import get_virtual_hosts
    vhosts = get_virtual_hosts()
    target = next((v for v in vhosts if v['domain'] == domain), None)
    
    if not target:
        return False, "Domain not found."

    try:
        # Update Apache
        if 'Apache' in target['servers']:
            path = target['config_paths'].get('Apache')
            if path and os.path.exists(path):
                with open(path, 'r') as f:
                    content = f.read()
                
                if enabled:
                    content = content.replace('SecRuleEngine Off\n', '')
                    content = content.replace('SecRuleEngine Off', '')
                else:
                    if 'SecRuleEngine Off' not in content:
                        # Inject before </VirtualHost>
                        content = content.replace('</VirtualHost>', '    SecRuleEngine Off\n</VirtualHost>')
                
                with open(path, 'w') as f:
                    f.write(content)

        # Update Nginx
        if 'Nginx' in target['servers']:
            path = target['config_paths'].get('Nginx')
            if path and os.path.exists(path):
                with open(path, 'r') as f:
                    content = f.read()
                
                if enabled:
                    content = content.replace('modsecurity off;\n', '')
                    content = content.replace('modsecurity off;', '')
                else:
                    if 'modsecurity off;' not in content:
                        # Inject before last }
                        content = re.sub(r'}\s*$', '    modsecurity off;\n}', content)
                
                with open(path, 'w') as f:
                    f.write(content)

        subprocess.run(['systemctl', 'reload', 'apache2'], capture_output=True)
        subprocess.run(['systemctl', 'reload', 'nginx'], capture_output=True)
        return True, f"ModSecurity {'enabled' if enabled else 'disabled'} for {domain}."
    except Exception as e:
        return False, str(e)

def get_modsec_config(file_type):
    paths = {
        'main': MODSEC_CONF_PATH,
        'custom': MODSEC_CUSTOM_RULES,
        'disabled': MODSEC_DISABLED_RULES
    }
    path = paths.get(file_type)
    if not path: return ""

    if not os.path.exists(path):
        # Create directory if needed
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # Touch file
        with open(path, 'a'): pass
        return ""

    try:
        with open(path, 'r') as f:
            return f.read()
    except Exception:
        return ""

def save_modsec_config(file_type, content):
    paths = {
        'main': MODSEC_CONF_PATH,
        'custom': MODSEC_CUSTOM_RULES,
        'disabled': MODSEC_DISABLED_RULES
    }
    path = paths.get(file_type)
    if not path: return False, "Invalid file type."

    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write(content)
        
        # Test config
        # apachectl configtest? 
        subprocess.run(['systemctl', 'reload', 'apache2'], capture_output=True)
        subprocess.run(['systemctl', 'reload', 'nginx'], capture_output=True)
        return True, f"ModSecurity {file_type} config saved successfully."
    except Exception as e:
        return False, str(e)

def get_modsec_audit_log(domain_filter=None):
    if not os.path.exists(MODSEC_AUDIT_LOG):
        return "Log file not found."

    try:
        # For audit logs, they can be huge. We'll take the tail.
        result = subprocess.run(['tail', '-n', '200', MODSEC_AUDIT_LOG], capture_output=True, text=True)
        lines = result.stdout.splitlines()
        
        if not domain_filter:
            return "\n".join(lines)
        
        # Simple string matching for domain if provided
        filtered = [l for l in lines if domain_filter in l]
        return "\n".join(filtered)
    except Exception:
        return "Error reading log."
