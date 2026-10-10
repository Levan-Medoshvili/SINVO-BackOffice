# Staging update preparation: no installation

Run the preparation worker manually using the existing `simplepos` service
account and identity. This is deliberately a separate one-shot process, not
an HTTP-triggered privileged operation.

```bash
# As root on an already-enrolled test host:
install -d -o simplepos -g simplepos -m 700 /var/lib/sinvo-backoffice/downloads
# copy sinvo_prepare.py and updated sinvo_download.py to /opt/sinvo-backoffice-client/
systemd-run --quiet --wait --pipe --collect --uid=simplepos --gid=simplepos \
  --property=WorkingDirectory=/opt/sinvo-backoffice-client \
  --setenv=PYTHONPATH=/opt/sinvo-backoffice-client \
  /opt/pos-erp/current/.venv/bin/python \
  /opt/sinvo-backoffice-client/sinvo_prepare.py \
  --downloads /var/lib/sinvo-backoffice/downloads
```

The worker reads the already provisioned identity and streams an approved
package to a private file, validating both byte count and SHA-256. It writes
private progress.json atomically to the existing update-client directory.
The BackOffice GUI can read only the public stage, percentage, message, and
release version via /system-updates/progress/.

Do not run with root privileges. This phase NEVER executes an archive,
extracts its contents, installs software, changes the database, or restarts
the web service. The displayed progress is real download preparation,
not simulated installation progress.

A future hardened installer will require cryptographic signing, independent
systemd privilege separation, schema-aware backups, health checks and recovery.
