"""Provision only the dedicated local ERP and disposable CI database roles."""
import json
from pathlib import Path
import subprocess
from configure import read_env


def psql(sql):
    result = subprocess.run(['runuser', '-u', 'postgres', '--', 'psql', '-X', '-qAt', '-v', 'ON_ERROR_STOP=1', '-d', 'postgres'], input=sql, text=True, capture_output=True)
    if result.returncode:
        # SQL can contain a password. Do not print SQL/stderr into the Jenkins log.
        raise SystemExit('PostgreSQL provisioning failed. Review PostgreSQL service logs on the server.')
    return result.stdout.strip()


def main():
    root = Path('/etc/pos-erp')
    marker = root / 'managed-postgres.json'
    state = json.loads(marker.read_text())
    app = read_env(root / 'backend.env')
    ci = read_env(root / 'ci.env')
    for values, name in [(app, 'simplepos_erp'), (ci, 'simplepos_erp_ci')]:
        if values.get('DB_ENGINE') != 'postgres' or values.get('DB_HOST') != '127.0.0.1' or values.get('DB_NAME') != name or values.get('DB_USER') != name:
            raise SystemExit('Managed PostgreSQL configuration changed; review it before provisioning.')
    if not state.get('initialized'):
        collision = psql("SELECT count(*) FROM pg_roles WHERE rolname IN ('simplepos_erp','simplepos_erp_ci');")
        databases = psql("SELECT count(*) FROM pg_database WHERE datname IN ('simplepos_erp','simplepos_erp_ci','test_simplepos_erp_ci');")
        if collision != '0' or databases != '0':
            raise SystemExit('ERP role/database names already exist. Nothing was reset; review ownership before continuing.')
        app_password = app['DB_PASSWORD'].replace("'", "''")
        ci_password = ci['DB_PASSWORD'].replace("'", "''")
        psql("SET password_encryption='scram-sha-256';\n"
             f"CREATE ROLE simplepos_erp LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD '{app_password}';\n"
             f"CREATE ROLE simplepos_erp_ci LOGIN NOSUPERUSER CREATEDB NOCREATEROLE CONNECTION LIMIT 10 PASSWORD '{ci_password}';\n"
             "CREATE DATABASE simplepos_erp OWNER simplepos_erp ENCODING 'UTF8' TEMPLATE template0;\n"
             "CREATE DATABASE simplepos_erp_ci OWNER simplepos_erp_ci ENCODING 'UTF8' TEMPLATE template0;\n")
        state['initialized'] = True
        marker.write_text(json.dumps(state))
    hba = Path('/var/lib/pgsql/data/pg_hba.conf')
    content = hba.read_text()
    if '# pos-erp dedicated local roles' not in content:
        hba.write_text('# pos-erp dedicated local roles\n'
                       'host simplepos_erp simplepos_erp 127.0.0.1/32 scram-sha-256\n'
                       'host postgres,simplepos_erp_ci,test_simplepos_erp_ci simplepos_erp_ci 127.0.0.1/32 scram-sha-256\n' + content)


if __name__ == '__main__':
    main()
