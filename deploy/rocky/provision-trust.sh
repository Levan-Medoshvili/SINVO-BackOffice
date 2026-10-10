#!/usr/bin/env bash
# Called by trusted BackOffice installation only, never by the update API.
set -euo pipefail
umask 077
[[ $EUID == 0 && $# == 1 ]] || { echo "Usage: provision-trust.sh TRUSTED_PUBLIC_KEY_RAW" >&2; exit 1; }
source_key=$1
[[ -f "$source_key" && ! -L "$source_key" ]] || { echo "Publisher public key not bundled; installer cannot enable updates." >&2; exit 1; }
[[ $(stat -c %s -- "$source_key") == 32 ]] || { echo "Ed25519 public key must be 32 bytes" >&2; exit 1; }
install -d -o root -g simplepos -m 710 /etc/pos-erp
destination=/etc/pos-erp/sinvo-signing-public.raw
if [[ -e $destination ]]; then
  cmp -s -- "$source_key" "$destination" || { echo "Trusted signing key differs: refusing implicit key rotation" >&2; exit 1; }
else
  install -o root -g simplepos -m 640 "$source_key" "$destination"
fi
echo "SINVO publisher trust anchor provisioned"
