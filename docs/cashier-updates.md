# Cashier updates

Status: v0.3 implements daily/manual signed release checks and **Update and restart**, gated on an empty basket, completed receipt handover, no printing/payment and no queued sales. The trusted starter verifies the complete archive, preserves the separate data directory and rejects downgrades. A ZIP alone does not configure release trust; see [installation and release publishing](cashier-access-and-installation.md). Branch-targeted required schedules, staged downloads during sales, rollout tracking and automatic rollback below remain planned. v0.2 requires one manual upgrade.

## Cashier preferences

- Show installed version, last successful check, available version, release notes, download/install status and the managed update source.
- Provide **Check for updates** regardless of the optional automatic-check preference.
- Automatic checks can be off or once daily at a configured time. Display the company's time zone; initially Asia/Tbilisi. A missed check runs on the next connection, with backoff/jitter on failures. Persist the last successful check and due time across restarts.
- Optional releases notify the cashier. The cashier can download, then choose **Update when checkout is free**. Optional automatic download is a separate preference and never grants permission to interrupt checkout.
- Turning off optional checks does not disable required server rollout delivery, device heartbeat or normal business synchronization. Make this visible beside the preference.

The actual operating system/architecture is detected by the installed client, not changed by a business preference. Any operating-system selector in the design preview only switches the simulated device.

## Server scheduling

A platform administrator publishes an immutable approved release and creates a required rollout: release ID, authorized company/branches, earliest installation date/time, IANA time zone, optional expiry, and audit reason/actor. Store the UTC instant plus the original time-zone information. An “all current branches” selection snapshots branch IDs; future branches are included only through a separate, explicit ongoing policy.

BackOffice uses the shared API to manage rollouts. Devices fetch durable policy by cursor on enrollment, heartbeat and reconnection. Push notifications can speed delivery, but cannot be the only delivery mechanism. Release publishing, company rollout scheduling and cashier preferences have separate permissions; a tenant user cannot target another company or publish executable packages.

Download the correct verified package in the background before the scheduled time when possible. At that time install only if the local safety gate passes. Busy terminals report **Waiting for checkout to finish**; they never interrupt a sale because a server deadline arrived. Offline devices cannot discover new schedules or download packages. A missed required schedule is fetched on reconnection and applied at the first safe idle period, unless it was cancelled, expired or superseded. A previously acknowledged, still-valid schedule with a verified cached package may run offline. Cancellation cannot reach an offline device immediately; show its last acknowledgement accurately.

Track each terminal separately: policy pending, scheduled, downloading, verified, waiting for checkout, installing, healthy, failed/rolled back, and offline with last-seen time. A rollout is successful only after the new application starts, passes local health checks and reports its installed version; starting a download is not success.

## Meaning of “no client”

Software cannot detect a physical customer. Use a local checkout safety gate:

1. No active basket, checkout reservation, suspended transaction requiring recovery, return/refund or cash-management operation is in progress. Parked baskets must first be durably saved in a format the new version can read.
2. No payment is pending or uncertain. An unknown bank outcome blocks installation until reconciliation; do not retry a charge to clear the gate.
3. Receipt/fiscal printing and device jobs are finished or durably recorded for safe recovery. Receipt handover is complete. In the design, **New sale** closes the completed customer's handover state.
4. No database transaction or synchronization write is in progress; acquire an exclusive local maintenance lock shared with sale creation and device work. Re-check the gate under that lock.
5. Persist local sale/payment state, the upload outbox, catalog cursors and settings; checkpoint/backup according to the chosen database's supported procedure. Pending uploads do not require internet if they are safely stored and compatible with the new version.

Show a 15-second idle countdown before acquiring the final maintenance lock. Scanning, starting a new sale or other checkout activity cancels the countdown and waits for the next idle period. Once the lock is acquired, block new checkout/payment work on both screens, display a short maintenance state, install and restart. This local lock prevents the race between a server instruction and a new customer scan.

## Package and recovery contract

- Distribute through the SimplePOS HTTPS update server with device-scoped authorization. Do not accept an arbitrary URL from the cashier. Release manifests bind product ID, version, OS, architecture, package format, byte size, digest and compatibility requirements.
- Authenticate manifests/packages with a trusted signing key and verify the digest and target platform before installation. A checksum alone does not authenticate a release. Use a stable internal application ID independent of the display name SimplePOS.
- Resume downloads, enforce storage limits, and retain the previous working package. Partial downloads and failed verification never replace the running application.
- Keep data outside the application install directory. Installer operations must never clear the local database, outbox, device identity or bank reconciliation records.
- Check free space and local schema/API compatibility before taking checkout offline. Prefer backward-compatible migrations. Roll back code only when the data format is compatible; never restore an old database over newer sales merely to roll back a binary.
- Persist update progress outside the replaceable binary. After power loss, recover the last valid install or resume the recorded operation. Failed installation/health checks retain recoverable sales and report an actionable status.
- Required updates cannot imply universal instant enforcement: disconnected and busy registers remain pending. Alert administrators about overdue terminals without cutting off an active sale.

## Windows and Linux

Use one update coordinator and platform-specific packaging/install adapters. Verify each supported package type in pilot. Electron's [built-in autoUpdater](https://www.electronjs.org/docs/latest/api/auto-updater), checked 2026-10-01, supports Windows/macOS and explicitly has no built-in Linux support. Choosing Electron therefore does not itself solve Linux updating. A Linux package-manager integration or a separately selected compatible updater is required. Avoid uncontrolled install-on-exit behavior that bypasses the local safety gate.

## Acceptance scenarios

- Manual checks work with automatic checks disabled; daily checks run at most once per due cycle and recover after a missed connection.
- A required rollout still arrives with optional checks off and affects only its scoped devices.
- A due update waits through a full sale, uncertain payment, printing and receipt handover. A new scan during the countdown postpones installation.
- A register that missed the scheduled time receives the policy on reconnect. A future schedule never installs early.
- Cancelled/expired/superseded policies are ignored once acknowledged; offline policy acknowledgements remain visible.
- Unsent offline sales survive restart, failed installation and supported rollback with the same IDs, and later synchronize once.
- Wrong platform, tampered package, insufficient disk, incompatible schema and interrupted download leave the previous working application available.

The design exercises manual checks, downloading, busy-sale and receipt-handover waits, idle countdowns and branch targeting. The installed pilot now has durable sales/queue recovery; its starter tests verify manifest signatures, package digests, failed-download preservation and offline cached launch. The v0.3 updater adds an in-app maintenance lock and signed release checks. The full scheduled-update service, native Windows starter execution and bank/printer coordination still require implementation or integration validation.

## v0.4 branch-targeted rollouts

BackOffice now has **Cashier updates → Import release**. Upload the Windows ZIP or Linux AppImage together with its signed `manifest.json` and `manifest.sig`. The server verifies the signature and full package SHA-256 and stores the version immutably. A version cannot be replaced with another package.

Configure `SIMPLEPOS_RELEASE_PUBLIC_KEY` (default `/etc/pos-erp/cashier-release-public.pem`) with your existing trusted RSA public key, readable by `simplepos`. Keep the private key with the release operator, outside both repositories and off the BackOffice server. Do not replace an existing key to resolve a signature error.

For a new installation with no signing key, create an RSA key of at least 3072 bits in a protected location, export only the public key to the server, and use the Cashier publisher:

```sh
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out cashier-release-private.pem
chmod 600 cashier-release-private.pem
openssl pkey -in cashier-release-private.pem -pubout -out cashier-release-public.pem
node tools/publish_cashier_release.cjs /path/to/SimplePOS-Cashier-0.4.0-win-x64.zip win-x64 0.4.0 /protected/cashier-release-private.pem /path/to/published
```

The publisher runs in the pos-cashier repository. It creates the signed package metadata, immutable `versions/VERSION/` files and a trusted starter with the public key pinned. For a starter's first installation, the release operator publishes the platform folder under the configured server release directory, preserving its root manifest, signature and package. BackOffice imports populate version-specific endpoints and do not alter the legacy latest-release endpoint.

Select the imported release in BackOffice, then choose all active branches or selected branches and push now or schedule a time in Asia/Tbilisi. A rollout captures the active POS terminals at creation; newly added terminals need another rollout. Known terminals for a different platform are excluded. The POS versions table shows last version/report and updater readiness. Devices poll every 30 seconds, including while signed out; offline devices catch up when reconnected. Failed checks retry after five minutes.

Installation waits for no basket, receipt handover, printing or unsynchronized sales. Statuses distinguish waiting, installing, installed and error. Cancel prevents updates that have not started; an already launched installer can finish. A new cancelled rollout never reactivates an older rollout.

**Existing v0.3 terminals need a one-time upgrade to Cashier v0.4 and the matching v0.4+ trusted starter.** Old starters do not support pinned target versions. The new starter writes updater protocol 2; do not edit an old starter's configuration to claim support. Use the same operating-system user profile to preserve the SQLite database, encrypted identity and credentials. A manually extracted ZIP works immediately; managed updates remain unavailable until its trusted updater is configured.

The managed Rocky proxy allows 1100 MB only at `/updates/import/`, 6 MB under `/advertisements/`, and uses a 300-second worker timeout. Apply equivalent limits to custom HTTPS proxies. Uploads are never executed by the importer. Windows packaging is verified on Linux; native Windows starter execution and the production Jenkins result require verification on the target environment.
