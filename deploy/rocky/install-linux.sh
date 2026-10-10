#!/usr/bin/env bash
# SINVO BackOffice fresh-host Linux installer.
# Default is read-only; installation requires explicit opt-in.
set -euo pipefail
umask 077

usage() {
  cat <<'USAGE'
SINVO BackOffice Linux installer (Staging pilot)

Usage:
  sudo bash install-linux.sh --detect
  sudo bash install-linux.sh --plan --ip 10.0.110.160 --allow-cidrs 10.0.110.0/24
  sudo bash install-linux.sh --install --ip 10.0.110.160 --allow-cidrs 10.0.110.0/24 --confirm-new-vm

Options:
  --detect               Print detected distribution and support status
  --plan                 Show what would be done; no host changes (default)
  --install              Install software and provision database (requires --confirm-new-vm)
  --confirm-new-vm       Confirm this is a disposable, clean test VM
  --ip IPv4              Private IPv4 address assigned to this VM
  --allow-cidrs CIDRS    Comma-separated private client IPv4 networks
  --help                 Display help

Supported automated install: Rocky Linux 9 with local PostgreSQL 16, HTTP
private-LAN pilot. Other distributions are detected but NOT installed.
Run this script from the root of a trusted SINVO BackOffice checkout.
No repository pull, remote code execution, or unattended upgrade occurs.
USAGE
}

die() { echo "SINVO installer: $*" >&2; exit 1; }
detect_os() {
  [[ -f /etc/os-release ]] || die "Cannot identify operating system"
  local ID="" VERSION_ID="" ID_LIKE="" PRETTY_NAME=""
  # /etc/os-release is defined as shell-compatible assignments.
  . /etc/os-release
  OS_ID=${ID:-unknown}
  OS_VERSION=${VERSION_ID:-unknown}
  OS_PRETTY=${PRETTY_NAME:-$OS_ID $OS_VERSION}
  OS_FAMILY=unsupported
  OS_SUPPORTED=0
  case "$OS_ID:$OS_VERSION" in
    rocky:9|rocky:9.*) OS_FAMILY=rhel9; OS_SUPPORTED=1;;
    almalinux:9|almalinux:9.*|rhel:9|rhel:9.*|centos:9|centos:9.*) OS_FAMILY=rhel9-compatible;;
    ubuntu:*|debian:*) OS_FAMILY=debian;;
  esac
}
show_detect() {
  printf 'Detected OS: %s\nOS ID: %s\nVersion: %s\nFamily: %s\n' "$OS_PRETTY" "$OS_ID" "$OS_VERSION" "$OS_FAMILY"
  if [[ $OS_SUPPORTED == 1 ]]; then
    echo "Automated installation: supported (Rocky Linux 9)"
  else
    echo "Automated installation: blocked (adapter not yet validated)"
  fi
}
require_fresh() {
  [[ ! -e /opt/pos-erp/current && ! -L /opt/pos-erp/current ]] || die "Existing BackOffice detected: refusing replacement"
  [[ ! -e /etc/pos-erp/backend.env ]] || die "Existing BackOffice configuration detected"
  [[ ! -e /etc/pos-erp/ci.env ]] || die "Existing BackOffice CI configuration detected"
  [[ ! -e /etc/pos-erp/managed-postgres.json ]] || die "Existing managed database detected"
  [[ ! -e /etc/nginx/conf.d/pos-erp.conf ]] || die "Existing Nginx BackOffice configuration detected"
  [[ ! -e /etc/simplepos/backend.env ]] || die "Legacy installation detected"
  [[ ! -e /var/lib/pgsql/data/PG_VERSION ]] || die "An existing PostgreSQL instance is present; manual review required"
  [[ ! -d /opt/pos-erp/releases || -z $(find /opt/pos-erp/releases -mindepth 1 -maxdepth 1 -print -quit) ]] || die "Release directory is not empty"
}
mode=plan ip="" cidrs="" confirmation=0
while (($#)); do
  case "$1" in
    --detect) mode=detect;;
    --plan) mode=plan;;
    --install) mode=install;;
    --confirm-new-vm) confirmation=1;;
    --ip) (($# >= 2)) || die "--ip requires a value"; ip=$2; shift;;
    --allow-cidrs) (($# >= 2)) || die "--allow-cidrs requires a value"; cidrs=$2; shift;;
    --help|-h) usage; exit 0;;
    *) die "Unknown argument: $1";;
  esac
  shift
done
detect_os
show_detect
[[ $mode == detect ]] && exit 0
[[ $OS_SUPPORTED == 1 ]] || die "No validated installer for $OS_PRETTY. Nothing was changed."
[[ $EUID == 0 ]] || die "Run as root with sudo"
[[ -n $ip && -n $cidrs ]] || die "Supply --ip and --allow-cidrs"
[[ $ip =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] || die "Invalid IPv4 syntax"
[[ $cidrs =~ ^[0-9.,/]+$ ]] || die "Invalid CIDR list syntax"
command -v python3 >/dev/null || die "Python 3 is needed for private IP validation"
python3 - "$ip" "$cidrs" <<'PY'
import ipaddress,sys
private=[ipaddress.ip_network(n) for n in ("10.0.0.0/8","172.16.0.0/12","192.168.0.0/16")]
ip=ipaddress.IPv4Address(sys.argv[1])
nets=[ipaddress.ip_network(v.strip(),strict=False) for v in sys.argv[2].split(",")]
if not any(ip in n for n in private) or not nets or any(n.version != 4 or not any(n.subnet_of(p) for p in private) for n in nets):
    raise SystemExit("Only private LAN IPv4 and private CIDRs are supported for the HTTP pilot")
PY
scripts="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd -- "$scripts/../.." && pwd)"
[[ -f "$root/backend/manage.py" && -f "$scripts/deploy.sh" && -f "$root/.python-version" ]] || die "Run from a complete SINVO checkout"
command -v git >/dev/null || die "Install git before running the installer"
git -C "$root" rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "Only a Git checkout is supported"
[[ -z $(git -C "$root" status --porcelain --untracked-files=no) ]] || die "Checkout contains uncommitted changes"
revision=$(git -C "$root" rev-parse --verify HEAD)
[[ $revision =~ ^[a-f0-9]{40}$ ]] || die "Cannot resolve revision"
require_fresh
echo "Install mode: $mode"
echo "App revision: $revision"
echo "Database: managed PostgreSQL 16 (dedicated application and CI databases)"
echo "Python: managed Python 3.14.8 virtual environment"
echo "Web server: Nginx + Gunicorn on private-LAN HTTP"
echo "Server IPv4: $ip"
echo "Allowed CIDRs: $cidrs"
echo "Installer will download build dependencies from OS/Python/PyPI repositories."
echo "Installer runs database provisioning, Django migrations and service startup."
echo "WARNING: This HTTP pilot is not suitable for public internet exposure."
[[ $mode == install ]] || { echo "PLAN ONLY: no changes made."; exit 0; }
[[ $confirmation == 1 ]] || die "Installation requires --confirm-new-vm"
# Source digest is for local deployment identity, not a publisher signature.
checksum=$(tar --sort=name --mtime='UTC 1970-01-01' --owner=0 --group=0 --numeric-owner -cf - -C "$root" backend | sha256sum | cut -d' ' -f1)
echo "Starting clean-VM deployment. This can take significant time..."
bash "$scripts/deploy.sh" "$root" "$revision" "$checksum" postgres "$ip" "$cidrs"
