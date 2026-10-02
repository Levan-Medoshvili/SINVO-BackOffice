#!/usr/bin/env bash
set -euo pipefail
umask 077
[[ $EUID == 0 && $# == 3 ]] || { echo 'Usage: prepare.sh DB_ENGINE SERVER_IP ALLOWED_CIDRS' >&2; exit 1; }
engine=$1
server_ip=$2
networks=$3
[[ $engine =~ ^(postgres|mysql|mssql)$ ]] || exit 1
source /etc/os-release
[[ $ID == rocky && $VERSION_ID == 9* ]] || { echo 'This installation targets Rocky Linux 9.' >&2; exit 1; }
scripts=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [[ ! -f /etc/pos-erp/backend.env && -f /etc/simplepos/backend.env ]]; then
 echo 'An older SimplePOS installation exists. Migrate its configuration/data before installing this server.' >&2; exit 1
fi
dnf install -y dnf-plugins-core
dnf config-manager --set-enabled crb
dnf install -y gcc make tar xz curl openssl-devel bzip2-devel libffi-devel zlib-devel xz-devel readline-devel sqlite-devel libuuid-devel libzstd-devel ncurses-devel nginx policycoreutils-python-utils util-linux sudo
case "$engine" in
 mysql) dnf install -y mariadb-connector-c-devel pkgconf-pkg-config ;;
 mssql)
  curl --fail --silent --show-error --location https://packages.microsoft.com/config/rhel/9/prod.repo -o /etc/yum.repos.d/microsoft-prod.repo
  ACCEPT_EULA=Y dnf install -y msodbcsql18 unixODBC-devel gcc-c++ ;;
esac
version=3.14.8
python=/opt/pos-erp-python/$version/bin/python3.14
if [[ ! -x $python ]]; then
 build=$(mktemp -d /var/tmp/pos-erp-python.XXXXXXXX)
 trap 'rm -rf -- "$build"' EXIT
 curl --fail --silent --show-error --location "https://www.python.org/ftp/python/$version/Python-$version.tar.xz" -o "$build/python.tar.xz"
 echo "c2215904f02b175596dc49351585104f4bc20341e1c47378b26a2c274360ce73  $build/python.tar.xz" | sha256sum --check --status
 tar -xf "$build/python.tar.xz" -C "$build"
 (cd "$build/Python-$version" && ./configure --prefix="/opt/pos-erp-python/$version" --with-ensurepip=install && make -j "$(nproc)" && make altinstall)
fi
"$python" -c 'import ssl,sqlite3,ctypes,bz2,lzma; print("Python runtime modules verified")'
id simplepos >/dev/null 2>&1 || useradd --system --home-dir /var/lib/pos-erp --shell /sbin/nologin simplepos
id pos-erp-build >/dev/null 2>&1 || useradd --system --create-home --home-dir /var/lib/pos-erp-build --shell /sbin/nologin pos-erp-build
install -d -o root -g root -m 755 /opt/pos-erp /opt/pos-erp/releases
install -d -o root -g root -m 700 /etc/pos-erp /var/backups/pos-erp
install -d -o simplepos -g simplepos -m 750 /var/lib/pos-erp /var/lib/pos-erp/static /var/lib/pos-erp/media /var/lib/pos-erp/cashier-releases
install -d -o pos-erp-build -g pos-erp-build -m 750 /var/lib/pos-erp-ci
"$python" "$scripts/configure.py" "$engine" "$server_ip" "$networks"
if [[ -f /etc/pos-erp/managed-postgres.json ]]; then
 if [[ -f /var/lib/pgsql/data/PG_VERSION && $(cat /var/lib/pgsql/data/PG_VERSION) != 16 ]]; then
  echo 'An existing PostgreSQL data directory uses a different major version; automatic upgrade is refused.' >&2; exit 1
 fi
 dnf module install -y postgresql:16/server
 dnf install -y postgresql postgresql-server
 [[ -f /var/lib/pgsql/data/PG_VERSION ]] || postgresql-setup --initdb
 systemctl enable --now postgresql
 "$python" "$scripts/provision_postgres.py"
 systemctl reload postgresql
fi
install -o root -g root -m 644 "$scripts/pos-erp.service" /etc/systemd/system/pos-erp.service
install -o root -g root -m 755 "$scripts/manage.sh" /usr/local/bin/pos-erp-manage
systemctl daemon-reload
if command -v selinuxenabled >/dev/null && selinuxenabled; then setsebool -P httpd_can_network_connect 1; fi
nginx -t
if systemctl is-active --quiet firewalld; then
 IFS=',' read -ra cidrs <<< "$networks"
 for cidr in "${cidrs[@]}"; do
  rule="rule family=ipv4 source address=$cidr port port=80 protocol=tcp accept"
  firewall-cmd --permanent --add-rich-rule="$rule"
  firewall-cmd --add-rich-rule="$rule"
 done
fi
echo 'Required packages, runtime and service configuration are ready.'
