"""Generate secrets once, preserve existing configuration, and render the LAN proxy."""
import ipaddress
import json
import os
from pathlib import Path
import secrets
import sys


def read_env(path):
    values = {}
    for line in path.read_text().splitlines():
        if line and not line.lstrip().startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            values[key] = value.strip().strip('"').strip("'")
    return values


def write_private(path, values):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as output:
        output.write(''.join(f'{key}={value}\n' for key, value in values.items()))
        output.flush()
        os.fsync(output.fileno())


def main():
    engine, server, allowed = sys.argv[1:]
    address = ipaddress.IPv4Address(server)
    private_ranges = [ipaddress.ip_network(cidr) for cidr in ['10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16']]
    if not any(address in block for block in private_ranges):
        raise SystemExit('The automatic HTTP pilot requires a private server IP.')
    networks = [ipaddress.ip_network(value.strip(), strict=False) for value in allowed.split(',')]
    if not networks or any(net.version != 4 or not any(net.subnet_of(block) for block in private_ranges) for net in networks):
        raise SystemExit('HTTP_ALLOWED_CIDRS must contain only private IPv4 networks.')
    root = Path('/etc/pos-erp')
    env = root / 'backend.env'
    if not env.exists():
        if engine != 'postgres':
            raise SystemExit('For MySQL/MSSQL, configure /etc/pos-erp/backend.env and ci.env using the example before deploying.')
        shared = {'SIMPLEPOS_SECRET_KEY': secrets.token_urlsafe(64), 'SIMPLEPOS_DEBUG': '0',
                  'SIMPLEPOS_BRAND': 'SimplePOS', 'SIMPLEPOS_ALLOWED_HOSTS': f'{server},127.0.0.1,localhost',
                  'SIMPLEPOS_CSRF_ORIGINS': f'http://{server}', 'SIMPLEPOS_HTTPS': '0',
                  'SIMPLEPOS_DATA_DIR': '/var/lib/pos-erp', 'SIMPLEPOS_OFFLINE_LOGIN_DAYS': '7',
                  'SIMPLEPOS_ALLOW_LEGACY_SALES': '0', 'SIMPLEPOS_RELEASE_DIR': '/var/lib/pos-erp/cashier-releases',
                  'DB_ENGINE': 'postgres', 'DB_HOST': '127.0.0.1', 'DB_PORT': '5432',
                  'DB_NAME': 'simplepos_erp', 'DB_USER': 'simplepos_erp', 'DB_PASSWORD': secrets.token_urlsafe(32),
                  'DB_SSLMODE': 'disable'}
        write_private(env, shared)
        ci = {**shared, 'SIMPLEPOS_SECRET_KEY': secrets.token_urlsafe(64), 'SIMPLEPOS_DEBUG': '1',
              'SIMPLEPOS_DATA_DIR': '/var/lib/pos-erp-ci', 'DB_NAME': 'simplepos_erp_ci',
              'DB_USER': 'simplepos_erp_ci', 'DB_PASSWORD': secrets.token_urlsafe(32)}
        write_private(root / 'ci.env', ci)
        write_private(root / 'initial-admin.env', {'DJANGO_SUPERUSER_USERNAME': 'admin',
                      'DJANGO_SUPERUSER_PASSWORD': secrets.token_urlsafe(24)})
        marker = root / 'managed-postgres.json'
        marker.write_text(json.dumps({'initialized': False}))
        marker.chmod(0o600)
    current = read_env(env)
    if current.get('DB_ENGINE') != engine:
        raise SystemExit('Selected DB_ENGINE differs from backend.env. Database conversion must be planned separately.')
    if current.get('SIMPLEPOS_HTTPS', '1') != '0':
        raise SystemExit('This automatic proxy is for the HTTP pilot. Preserve the existing HTTPS configuration and use its deployment procedure.')
    if server not in current.get('SIMPLEPOS_ALLOWED_HOSTS', '').split(','):
        raise SystemExit('Add the target IP to backend.env before changing servers.')
    proxy = Path('/etc/nginx/conf.d/pos-erp.conf')
    marker = '# Managed by pos-erp deployment'
    if proxy.exists() and marker not in proxy.read_text():
        raise SystemExit('An unrelated pos-erp.conf already exists; refusing to overwrite it.')
    rules = ''.join(f'    allow {network};\n' for network in networks)
    rendered = marker + '\nserver {\n    listen 80;\n    server_name ' + server + ';\n' + rules + '''    allow 127.0.0.1;
    deny all;
    client_max_body_size 2m;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 65s;
    }
}
'''
    proxy.write_text(rendered)
    proxy.chmod(0o644)


if __name__ == '__main__':
    main()
