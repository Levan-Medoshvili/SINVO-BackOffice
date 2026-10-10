# Phase 3: verified BackOffice packages (Staging only)

- Each new Jenkins Staging archive contains backend/.sinvo-build.json with
  its published semantic release version and matching commit revision.
- Legacy installed Git revisions have no build marker: their version is
  "Legacy / unversioned". They must not claim to run a published release.
- The 15-minute client reports an empty version on legacy installations.
  The Update Server currently treats an empty version as eligible for a newer
  approved release; this does not activate or install anything.
- The independent download CLI requires the existing approved client identity,
  verifies entitlement, product, channel, fixed server download path, size and
  SHA256. Output remains an inert, untrusted archive in a dedicated directory.
  It must never be unpacked or executed automatically.
- Future stage: independently operating installer, release signatures,
  backup hooks, health verification, maintenance gating, explicit admin approval
  and progress persisted beyond web-process restarts.

Example after the client has enrolled:

```sh
install -d -o simplepos -g simplepos -m 700 /var/lib/sinvo-backoffice/downloads
# Run from /opt/pos-erp/current/backend using the existing simplepos service
# environment, and set PYTHONPATH to the current backend path.
python sinvo_download.py --directory /var/lib/sinvo-backoffice/downloads
```
