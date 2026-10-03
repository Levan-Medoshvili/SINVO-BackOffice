#!/usr/bin/env bash
set -euo pipefail
umask 077
[[ $EUID == 0 && $# == 6 ]] || { echo 'Usage: deploy.sh SOURCE COMMIT SHA256 ENGINE SERVER_IP CIDRS' >&2; exit 1; }
source_dir=$1
revision=$2
checksum=$3
engine=$4
server_ip=$5
networks=$6
[[ $revision =~ ^[0-9a-f]{40}$ && $checksum =~ ^[0-9a-f]{64}$ && $engine =~ ^(postgres|mysql|mssql)$ ]] || exit 1
exec 9>/run/lock/pos-erp-deploy.lock
flock -n 9 || { echo 'Another ERP deployment is running.' >&2; exit 1; }
scripts=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
bash "$scripts/prepare.sh" "$engine" "$server_ip" "$networks"
python=/opt/pos-erp-python/3.14.8/bin/python3.14
release=/opt/pos-erp/releases/$revision
previous=$(readlink -f /opt/pos-erp/current || true)
if [[ ! -f $release/.prepared ]]; then
 if [[ -d $release ]]; then
  [[ $release != "$previous" ]] || { echo 'Current release is incomplete; manual recovery required.' >&2; exit 1; }
  rm -rf -- "$release"
 fi
 install -d -o pos-erp-build -g pos-erp-build -m 755 "$release"
 cp -a "$source_dir/backend" "$release/backend"
 chown -R pos-erp-build:pos-erp-build "$release"
 chmod -R a+rX "$release"
 runuser -u pos-erp-build -- "$python" -m venv "$release/.venv"
 runuser -u pos-erp-build -- "$release/.venv/bin/python" -m pip install --disable-pip-version-check -r "$release/backend/requirements-$engine.txt"
 printf '%s\n%s\n' "$checksum" "$engine" > "$release/.prepared"
 chown -R root:root "$release"
 chmod -R a+rX,go-w "$release"
fi
[[ $(sed -n '1p' "$release/.prepared") == "$checksum" && $(sed -n '2p' "$release/.prepared") == "$engine" ]] || { echo 'Existing release differs from the requested artifact/engine.' >&2; exit 1; }
[[ -f /etc/pos-erp/ci.env ]] || { echo 'Create a separate /etc/pos-erp/ci.env for the selected disposable database before deployment.' >&2; exit 1; }
"$python" - "$scripts" "$engine" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from configure import read_env
app = read_env(Path('/etc/pos-erp/backend.env'))
ci = read_env(Path('/etc/pos-erp/ci.env'))
if ci.get('DB_ENGINE') != sys.argv[2] or not ci.get('DB_NAME', '').endswith('_ci') or ci.get('DB_NAME') == app.get('DB_NAME') or ci.get('DB_USER') == app.get('DB_USER'):
    raise SystemExit('CI requires a separate *_ci database and login. Production credentials cannot run tests.')
PY
test_manage() {
 systemd-run --quiet --wait --pipe --collect --uid=pos-erp-build --gid=pos-erp-build \
  --property=EnvironmentFile=/etc/pos-erp/ci.env --property="WorkingDirectory=$release/backend" \
  --property=NoNewPrivileges=yes --setenv=PYTHONDONTWRITEBYTECODE=1 \
  "$release/.venv/bin/python" manage.py "$@"
}
test_manage makemigrations --check --dry-run
test_manage test commerce backoffice --noinput
manage() {
 systemd-run --quiet --wait --pipe --collect --uid=simplepos --gid=simplepos \
  --property=EnvironmentFile=/etc/pos-erp/backend.env --property="WorkingDirectory=$release/backend" \
  --property=NoNewPrivileges=yes --setenv=PYTHONDONTWRITEBYTECODE=1 \
  "$release/.venv/bin/python" manage.py "$@"
}
manage check
was_active=0
if systemctl is-active --quiet pos-erp; then was_active=1; systemctl stop pos-erp; fi
backup_ok=0
if [[ -f /etc/pos-erp/managed-postgres.json && $engine == postgres ]]; then
 backup="/var/backups/pos-erp/$(date -u +%Y%m%dT%H%M%SZ)-$revision.dump"
 if runuser -u postgres -- pg_dump --format=custom --no-owner --no-acl simplepos_erp > "$backup" && pg_restore --list "$backup" >/dev/null; then
  sha256sum "$backup" > "$backup.sha256"
  backup_ok=1
  echo "Database backup: $backup"
 fi
elif [[ -x /etc/pos-erp/backup-before-deploy && $(stat -c '%U' /etc/pos-erp/backup-before-deploy) == root ]]; then
 if /etc/pos-erp/backup-before-deploy; then backup_ok=1; fi
fi
if [[ $backup_ok != 1 ]]; then
 [[ $was_active == 0 ]] || systemctl start pos-erp
 echo 'Backup failed or no backup hook is configured. No migrations were run.' >&2; exit 1
fi
if ! manage migrate --noinput || ! manage collectstatic --noinput; then
 echo 'Migration/static collection failed. Service remains stopped; inspect the backup and schema before recovery.' >&2; exit 1
fi
printf 'SIMPLEPOS_BUILD_REVISION=%s\n' "$revision" > /etc/pos-erp/release.env
next_link="/opt/pos-erp/current.$revision.$$"
ln -s "$release" "$next_link"
mv -Tf "$next_link" /opt/pos-erp/current
systemctl enable pos-erp >/dev/null
systemctl restart pos-erp
systemctl enable --now nginx
systemctl reload nginx
healthy=0
for attempt in {1..15}; do
 if curl --fail --silent --max-time 3 http://127.0.0.1:8000/healthz/ | "$python" -c 'import json,sys; data=json.load(sys.stdin); assert data["status"] == "ok" and data.get("build_revision") == sys.argv[1]' "$revision" 2>/dev/null; then healthy=1; break; fi
 sleep 2
done
if [[ $healthy != 1 ]]; then
 echo "Health verification failed. Previous code: ${previous:-none}. Database rollback is never automatic." >&2; exit 1
fi
curl --fail --silent --show-error --max-time 10 -H "Host: $server_ip" http://127.0.0.1/healthz/ | "$python" -c 'import json,sys; data=json.load(sys.stdin); assert data["status"] == "ok" and data.get("build_revision") == sys.argv[1]' "$revision"
curl --fail --silent --show-error --location --max-time 10 -H "Host: $server_ip" http://127.0.0.1/login/ >/dev/null
echo "DEPLOYED_REVISION=$revision"
echo "ERP is ready at http://$server_ip/"
echo 'First setup: read /etc/pos-erp/setup.env as root, then create the company and administrator in the browser. Existing accounts are preserved.'
