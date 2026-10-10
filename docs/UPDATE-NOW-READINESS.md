# Update Now readiness (Staging)

The completed authenticated download and SHA-256 preparation pipeline is not
yet sufficient for executing release archives.

Run `python3 backend/sinvo_install_preflight.py` to inspect the target.
It never writes, invokes shell commands, restarts a service or modifies a DB.

Currently it deliberately reports `ready_to_install: false` until:
1. Update Server publishes signed manifests from an offline-controlled key;
2. an independent, limited-privilege installer validates that signature;
3. the backup strategy and migration recovery are tested against a disposable
   copy of the installed database;
4. a mutually exclusive, audited installation job is implemented;
5. a protected superuser web endpoint queues (not executes) the update job;
6. browser progress survives BackOffice restart and reports health check result.

Existing deploy/rocky/deploy.sh is NOT suitable as an HTTP request handler.
It invokes prepare.sh, uses separate CI credentials, stops the live service,
runs migrations and cannot safely reverse arbitrary schema changes.
Never point a web endpoint at this script.

The test host 10.0.110.151 should remain unchanged until this procedure
passes on the new disposable BackOffice installation.
