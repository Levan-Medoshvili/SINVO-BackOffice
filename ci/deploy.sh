#!/usr/bin/env bash
# Run only by the trusted Production Jenkins job, using its username/password binding.
set -euo pipefail
set +x
umask 077
host=${TARGET_HOST:-10.0.110.151}
engine=${DB_ENGINE:-postgres}
networks=${HTTP_ALLOWED_CIDRS:-10.0.0.0/8}
[[ $host =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ && $engine =~ ^(postgres|mysql|mssql)$ && $networks =~ ^[0-9./,]+$ ]] || { echo 'Invalid deployment parameters.' >&2; exit 1; }
[[ ${POS_SSH_USER:-} =~ ^[a-z_][a-z0-9_-]*$ && -n ${POS_SSH_PASSWORD:-} ]] || { echo 'Bind the pos_server_creds username/password credential.' >&2; exit 1; }
revision=$(git rev-parse HEAD)
[[ $revision =~ ^[0-9a-f]{40}$ ]] || exit 1
expected=$(git rev-parse refs/remotes/origin/Production 2>/dev/null || git rev-parse refs/heads/Production)
[[ $revision == "$expected" ]] || { echo 'Only the checked-out Production revision may deploy.' >&2; exit 1; }
checksum=$(cut -d ' ' -f 1 "artifacts/$revision.sha256")
[[ $checksum =~ ^[0-9a-f]{64}$ ]] || exit 1
askpass_dir=$(mktemp -d)
trap 'rm -rf -- "$askpass_dir"' EXIT
cat > "$askpass_dir/askpass" <<'SH'
#!/bin/sh
printf '%s\n' "$POS_SSH_PASSWORD"
SH
chmod 700 "$askpass_dir/askpass"
export SSH_ASKPASS="$askpass_dir/askpass" SSH_ASKPASS_REQUIRE=force DISPLAY=pos-erp:0
# Trust a new host on first connection and pin it in the Jenkins OS user's persistent
# known_hosts. Changed keys are rejected. Administrators can preinstall a verified key.
mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
options=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 -o ConnectionAttempts=1 -o NumberOfPasswordPrompts=1 -o PreferredAuthentications=password,keyboard-interactive -o PubkeyAuthentication=no -o ServerAliveInterval=20 -o ServerAliveCountMax=6)
remote="${POS_SSH_USER}@${host}"
stage=$(ssh "${options[@]}" "$remote" 'umask 077; test "$(id -u)" -eq 0 && mktemp -d /var/tmp/pos-erp-deploy.XXXXXXXX' </dev/null)
[[ $stage =~ ^/var/tmp/pos-erp-deploy\.[A-Za-z0-9]+$ ]] || { echo 'Root SSH access is required for initial package installation.' >&2; exit 1; }
scp "${options[@]}" "artifacts/$revision.tar.gz" "$remote:$stage/release.tar.gz" </dev/null
ssh "${options[@]}" "$remote" "bash -s -- '$stage' '$revision' '$checksum' '$engine' '$host' '$networks'" <<'REMOTE'
set -euo pipefail
umask 077
stage=$1
revision=$2
checksum=$3
engine=$4
host=$5
networks=$6
trap 'rm -rf -- "$stage"' EXIT
echo "$checksum  $stage/release.tar.gz" | sha256sum --check --status
mkdir "$stage/source"
python3 - "$stage/release.tar.gz" "$stage/source" <<'PY'
import sys, tarfile
from pathlib import PurePosixPath
with tarfile.open(sys.argv[1], 'r:gz') as archive:
    members = archive.getmembers()
    if len(members) > 10000 or sum(m.size for m in members) > 512 * 1024 * 1024:
        raise SystemExit('Archive is too large')
    for member in members:
        p = PurePosixPath(member.name)
        if p.is_absolute() or '..' in p.parts or member.issym() or member.islnk() or not (member.isdir() or member.isfile()):
            raise SystemExit('Unsupported archive entry')
        if not p.parts or p.parts[0] not in {'backend', 'deploy', '.python-version'}:
            raise SystemExit('Unexpected archive root')
    archive.extractall(sys.argv[2])
PY
bash "$stage/source/deploy/rocky/deploy.sh" "$stage/source" "$revision" "$checksum" "$engine" "$host" "$networks"
REMOTE
