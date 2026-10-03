# Cashier v0.3 — installation, approval and updates

Deploy the v0.3 ERP and run its migrations before connecting a new v0.3 POS. Existing enrolled v0.2 devices retain their identity and sales history. The [Rocky/Jenkins guide](https://github.com/Levan-Medoshvili/pos-erp/blob/Production/docs/deployment.md) covers server deployment.

## BackOffice setup

Open **http://10.0.110.151/** after Jenkins succeeds. New installations ask for the setup key from `sudo cat /etc/pos-erp/setup.env`, then the English/Georgian company names, administrator email, username and password. Address, phone and administrator names are optional. Existing installations with a company and administrator keep their credentials. Update missing company information in **Company settings**.

The custom BackOffice replaces Django admin. Create branches/warehouses, categories and products there. Products require an initial location. Opening quantity creates an audited stock adjustment. Inventory assignments make the same product available at additional locations; published prices and historical sales remain separate.

## Authorize a new POS

Device approval and employee sign-in are separate. The employee password alone cannot register an unknown POS.

**Request approval from Cashier**

1. Enter `http://10.0.110.151`, branch name and optional address. Enable the private-LAN HTTP option for this test server.
2. Choose **Request approval**. Cashier displays its unique device ID and waits.
3. In BackOffice → **Branches**, review **Pending POS requests**. Verify the device ID with the store.
4. Approve and create the requested branch, or select an existing branch before approving. Requests expire after 24 hours.
5. On the POS, press **Check approval**, then sign in.

**Use a BackOffice pairing code**

1. Add a branch in BackOffice, or use an existing active branch.
2. Choose **Generate code** beside the branch. The five-character code expires in ten minutes and authorizes one POS. Generating another code invalidates the branch's previous unused code.
3. On Cashier, enter the server, choose **I have a pairing code**, and enter the code. The server supplies the approved branch name.
4. Sign in with an employee account. Codes do not replace employee credentials.

Several POS terminals can belong to one branch; approve each device or generate a fresh code for each. Disable an unwanted terminal in **POS terminals**. Rejected requests remain rejected until they expire; an administrator can instead issue an authorized pairing code.

## Users, groups and supervision

Create users under **Users** and choose Backend, Cashier or Both. Permit one branch, several branches or all branches. A first online sign-in downloads the branch catalog and caches an OS-encrypted password verifier and bounded authorization (seven days by default). An explicit server denial never falls back to cached access. Offline revocation takes effect when the device reconnects or its authorization expires.

Groups add permissions to direct user permissions. Management permissions cover catalog, locations/approvals, inventory, users/groups and sales reports. `manage_users` is an administrative privilege that can delegate access; grant it only to trusted administrators. Branch restrictions apply to cashier sign-in, sales reports and checkout supervision; catalog, inventory and configuration management permissions operate across the installation.

Cashiers without `remove_basket_line` cannot reduce quantities or remove items locally. A supervisor with Backend/Both and `supervise_basket` selects a branch/POS under **Live checkouts**, enters a reason and requests removal. The request is **pending** until the POS confirms it. A changed basket/version, paid receipt, stale view or expired command is rejected rather than removing another customer's item. Refresh the page to see the confirmation.

## Upgrade the POS from v0.2

v0.2 has no in-app updater. One manual upgrade or trusted starter launch is necessary:

1. Finish the current customer, start a new sale and synchronize all queued sales. Close Cashier.
2. Back up the complete per-user application data folder while Cashier is closed: Windows `%APPDATA%\SimplePOS Cashier`; Linux `$XDG_CONFIG_HOME/SimplePOS Cashier` or `~/.config/SimplePOS Cashier`.
3. Extract the entire v0.3 Windows ZIP into a stable writable application folder. Run **SimplePOS Cashier.exe** using the same OS account.
4. Keep the existing data folder and credential vault. Do not copy just the SQLite file to another account or erase it to resolve connection problems.
5. Sign in online and verify the branch, catalog, sales history and pending count.

The Windows executable is unsigned. This portable ZIP does not configure a trusted release feed by itself. The NSIS installer is built on the Windows Jenkins agent; Linux uses the AppImage target. Bank/fiscal integration and model-specific printer drivers remain separate validation work.

## Preferences

- Start when the OS user signs into Windows or the Linux desktop.
- Open Cashier fullscreen; F11 toggles fullscreen.
- Open the customer display at startup (uses another monitor when available).
- Language, receipt printer, daily update checks or manual-only.
- **Server address**: change this installation's IP/hostname. Finish the customer and synchronize all sales first. The new server must report the same company/installation identity. Cashier preserves its device credential and history, clears cached sign-ins and requires an online sign-in again. A different company needs a separate POS profile.

The initial connection uses HTTPS by default. HTTP is an explicit option only for private-IP pilot testing. Install TLS before using the system outside the isolated test network.

## Configure trusted downloads once

A release operator generates a persistent private key on a protected signing/build machine. Keep it out of GitHub and the ERP server. Store it in Jenkins as secret-file credential `simplepos_release_key` to use the optional signing stage on a trusted Production branch.

```bash
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out simplepos-release-private.pem
node tools/publish_cashier_release.cjs /path/to/SimplePOS-Cashier-0.3.0-win-x64.zip win-x64 0.3.0 simplepos-release-private.pem published
```

For Linux, use the AppImage artifact and `linux-x64`. The publisher creates a package, signed manifest, detached signature and a small starter with the pinned public key. Serve the platform directories from `/var/lib/pos-erp/cashier-releases/` with read access for `simplepos` and write access only for the release operator. Publish complete directories together so package/manifest/signature match. URLs are `/cashier/releases/win-x64/…` and `/cashier/releases/linux-x64/…`.

Deliver `SimplePOS-Start.ps1` (Windows) or `SimplePOS-Start.py` (Linux) to the POS through your trusted administrator distribution. Review/trust the starter before running it. Windows requires PowerShell 5.1/.NET Framework 4.8 and permission to run the trusted script; Linux requires Python 3 and OpenSSL. No execution-policy bypass is built into Cashier.

Run the starter once with checkout closed. It downloads and verifies the archive, stores releases separately from POS data, installs the updater's public-key configuration and opens Cashier. Later starts can use the cached release offline. When moving from the standalone ZIP to the starter for the first time, enter the same server address if asked. It uses the same per-user data folder and does not erase the existing register identity.

## Test an update

Publish a higher-version build with the same signing key. In Cashier → **Preferences**, press **Check for updates**, then **Update and restart**. Installation is blocked while a basket, receipt handover, printing, payment or unsynchronized sale exists. Start a new sale and sync before retrying. The starter waits for Cashier to exit, re-verifies the signature and artifact, switches the active release only on success, and reopens it.

Failed downloads preserve the old release and local data; relaunch the starter without its download flag to open the cached release. A signed downgrade is rejected. Native Windows execution still needs testing on POSIFLEX. Branch-targeted required schedules, automated rollback and billing enforcement are not implemented in v0.3.

For v0.1 migration only, retained legacy sales may require the documented temporary `SIMPLEPOS_ALLOW_LEGACY_SALES` recovery setting. Keep it off during normal operation; never delete an unsynchronized sale to make an upgrade pass.
