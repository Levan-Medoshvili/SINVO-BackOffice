# SINVO BackOffice automatic enrollment - Staging

**No customer token generation required.** The first client run automatically
creates an installation UUID and 48-byte random credential, stores them in a
persistent, private file and submits ONLY the credential's SHA-256 digest.
The real credential never crosses the wire during the unauthenticated enrollment
request. Subsequent API calls use HTTPS Bearer authentication.

The initial Staging client is a standalone scheduled-command component so
it never blocks Django web startup or sales processing. No package is
automatically downloaded or installed.

On a **test BackOffice installation**, after ensuring DNS/TLS to the dev
Update Server and choosing a dedicated service account that can write its
persistent identity directory, run:

```bash
cd /path/to/backoffice/backend
SINVO_CLIENT_IDENTITY_FILE=/var/lib/sinvo-backoffice/update-client/identity.json \
SINVO_INSTALLATION_NAME="SINVO BackOffice Staging" \
python3 sinvo_enrollment.py
```

The device appears under Connected Installations > Pending.
Approving on dev-updates.sinvo.ge enables the next run's heartbeat and
release discovery. Schedule this command every 15 minutes via a dedicated
systemd service/timer once confirmed working. Keep the identity directory
outside application code and backups with appropriately restricted permissions.

Existing manually provisioned installations are different identities:
avoid using the same display name to confuse which installation was approved.

If the identity is lost, the server-side UUID cannot be reclaimed merely
by presenting a new secret; support must revoke the old record and approve
a new identity. No live deployment of BackOffice is changed by this commit.
