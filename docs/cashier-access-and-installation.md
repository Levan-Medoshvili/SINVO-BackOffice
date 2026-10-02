# Cashier v0.2: installation, users and supervision

Deploy the v0.2 backend and run its migrations **before** opening the v0.2 Cashier. Start with a test company and cash test sales. The [Rocky/Jenkins guide](https://github.com/Levan-Medoshvili/pos-erp/blob/Production/docs/deployment.md) covers server preparation and deployment.

## Prepare users in BackOffice

Sign in at `/admin/` as the platform administrator. Create the company, branches and products first. A product needs an initial branch or warehouse; add a Stock item to make it available at another location. A warehouse cannot enroll a checkout register.

In **Users → Add user**, enter the username/password and configure Employee access on the same form:

| Field | Meaning |
| --- | --- |
| Company | The company this employee belongs to |
| Application | Backend, Cashier or Both |
| All branches | Permits the company's current and future active branches |
| Branches | Select one or several when All branches is off; an empty selection permits none |
| Groups | Company-specific access groups |
| Permissions | Direct permissions added to the group's permissions |

In **Access groups**, create a group, select its company, permissions and members. Cross-company branches, groups and members are rejected. The initial permission codes are:

- `remove_basket_line`: permits a cashier to reduce a quantity or remove an unpaid item.
- `supervise_basket`: permits a Backend/Both user to view and request removal from live checkouts in their assigned branches.

A Backend/Both employee receives the staff flag automatically. General inventory, employee and group administration remains restricted to the platform administrator in this pilot. A supervisor needs Backend/Both and `supervise_basket`; Cashier-only users cannot enter BackOffice. Set a user inactive to disable access while retaining history. Ordinary cashiers should have neither permission unless their duties require it.

## Install on Windows 64-bit

For the supplied full package, extract **all** of `SimplePOS-Cashier-0.2.0-win-x64.zip` into a stable folder and run `SimplePOS Cashier.exe`. The package includes its desktop runtime. A Windows Jenkins agent can also build the NSIS installer.

First setup asks for:

1. **Branch name or code**: required; match exactly one existing branch in the employee's company.
2. **Branch address**: optional; saved as an enrollment hint. It does not change the central branch address.
3. **Server address**: required, such as `https://pos.example.ge`. For an isolated test LAN, an explicit checkbox allows HTTP to a private IP.

Connect to the server, then enter the cashier's username and password. The backend checks application and branch access, enrolls one register for this installation, and downloads the catalog. Subsequent sign-ins reuse the register. Give it a recognizable name in BackOffice, for example “Vake / Till 2”. An ambiguous branch name should be replaced by its unique code.

In **Preferences**, choose Start when OS starts, Fullscreen, and Open customer display automatically. Fullscreen and automatic customer display default on; OS startup defaults off. Startup means login to the configured Windows/Linux desktop user. The POS still requires a cashier sign-in. On a second extended display the customer window opens fullscreen; with one display it opens as a test window. F11 toggles fullscreen temporarily.

Keep the extracted application in its permanent location when enabling OS startup. On Linux, install the AppImage and use a desktop session with an unlocked secure keyring; plaintext credential storage is refused. Autostart uses the current user's XDG desktop entry. Verify Windows sign-in startup and both displays on the POSIFLEX before a store trial.

## Offline use and existing installations

The first sign-in requires the server. After a successful online sign-in, the same user can sign in offline using a locally encrypted password verifier and a bounded authorization. The default is **7 days**, configurable centrally with `SIMPLEPOS_OFFLINE_LOGIN_DAYS` from 1 to 30. Five wrong offline passwords cause a five-minute delay. An explicit online access denial clears that cached login. Branch/permission changes reach online devices through the heartbeat; disconnected devices retain their last authorization until expiry.

Closing Cashier or choosing Sign out locks it locally and retains the offline login cache. An unfinished basket stays with its original cashier. A new cashier cannot take it over. Cashier identity is attached to every completed sale. Already completed offline sales retain their original authorization and must upload within 30 days after its expiry; late/rejected entries remain queued for review.

Before upgrading a v0.1 POS, finish its basket and receipt handover, synchronize pending sales, close Cashier and back up its entire data directory. Deploy backend migrations and create the employee account. Open v0.2 under the **same OS account** with the same data directory and sign in online. It binds the existing register credential to the installation and preserves local sales and settings. Do not create a replacement database to clear an error.

If a v0.1 queue could not be drained before the server upgrade, an administrator can temporarily set `SIMPLEPOS_ALLOW_LEGACY_SALES=1`, restart the backend, synchronize those unchanged legacy payloads and verify their IDs/stock movements. Return the setting to `0` afterwards. This compatibility switch accepts sales without cashier identity and is off by default.

Windows data is in `%APPDATA%\SimplePOS Cashier\`; Linux uses the corresponding Electron user-data directory, normally `~/.config/SimplePOS Cashier/`. Back up with Cashier closed, including SQLite WAL files. Device secrets use OS credential storage; copying data to a different OS user or machine needs an enrollment recovery procedure.

## Remove an item remotely

In BackOffice, open **Live checkouts**, filter by branch and select the register. The page shows cashier, basket, connection freshness and command history. Choose a line, enter a reason and request removal. Refresh to see the result.

The POS exchanges snapshots and commands about every two seconds while connected. A request targets one basket UUID, revision and line; it expires after 90 seconds. BackOffice permits requests only for a fresh active basket seen within 15 seconds. If the basket changes, becomes locked or is paid before delivery, the POS rejects the command. A successful POS removal and its acknowledgment are stored together; retries cannot remove a second item. The cashier sees a supervisor notice and both screens update. **Pending is not a confirmation**. Completed sales remain immutable.

## Small first-download starter

The full ZIP works now without a download server. The repository also provides small Windows PowerShell and Linux Python starters. A release operator generates them with a pinned public key; on first launch they collect branch/server details, verify the server, download a signed release, verify size/SHA-256, install into a separate cache, then open Cashier at login. Later launches use the verified cached application offline.

Run the publisher from the root of the [pos-cashier repository](https://github.com/Levan-Medoshvili/pos-cashier). Generate a persistent signing key once on a protected release/build machine, with OpenSSL installed:

```bash
umask 077
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out simplepos-release-private.pem
node tools/publish_cashier_release.cjs /path/to/SimplePOS-Cashier-0.2.0-win-x64.zip win-x64 0.2.0 simplepos-release-private.pem published
# After building a Linux AppImage:
node tools/publish_cashier_release.cjs /path/to/SimplePOS-Cashier-0.2.0-linux-x64.AppImage linux-x64 0.2.0 simplepos-release-private.pem published
```

Keep the private key off POS devices, web servers and git. Protect and back it up; existing starters trust this key. The publisher creates each platform's application, `manifest.json`, `manifest.sig`, and a starter containing only the public key. The manifest signature authenticates the download; it does not Authenticode-sign the Windows executable or script.

On the server, copy the published platform directories to `/var/lib/pos-erp/cashier-releases/`, with read access for the `simplepos` service and write access only for the release operator. Set `SIMPLEPOS_RELEASE_DIR` to that path. Files are available through `/cashier/releases/win-x64/…` and `/cashier/releases/linux-x64/…`. Nginx forwards these routes to Django with the existing backend configuration. This initial feed serves public application binaries and no customer or device data. Publish a complete platform directory together, preferably by switching a prepared directory during a maintenance window, so clients cannot fetch mismatched manifest/signature pairs.

Distribute the generated starter through your trusted installation channel. Windows requires PowerShell 5.1 and .NET Framework 4.8. Review/unblock the trusted script according to your organization's execution policy, then run:

```powershell
powershell.exe -NoProfile -File .\SimplePOS-Start.ps1
```

Linux requires Python 3, OpenSSL, an AppImage-compatible desktop and a secure keyring; Tk provides the setup window, with terminal input as a fallback:

```bash
python3 SimplePOS-Start.py
```

For a manual maintenance download, close Cashier after finishing the customer and preserving the queue, then use `-DownloadLatest` on Windows or `--download-latest` on Linux. Failed verification keeps the active release pointer unchanged. Cached releases and POS data are separate. The starter has no checkout-aware in-app update coordinator, automatic rollback, required rollout scheduling or anti-rollback policy beyond the v0.2 minimum. See [the update design](cashier-updates.md) for that next phase. Native Windows starter execution still needs testing on the POS.
