#!/usr/bin/env bash
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Use sudo pos-erp-manage COMMAND.' >&2; exit 1; }
exec systemd-run --quiet --wait --pty --collect --uid=simplepos --gid=simplepos \
  --property=EnvironmentFile=/etc/pos-erp/backend.env \
  --property=WorkingDirectory=/opt/pos-erp/current/backend \
  --setenv=PYTHONDONTWRITEBYTECODE=1 \
  /opt/pos-erp/current/.venv/bin/python manage.py "$@"
