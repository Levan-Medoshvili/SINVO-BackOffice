# SINVO publisher-managed signing

Customers NEVER generate signing keys. SINVO operations runs publisher
bootstrap once in a secured management environment and provisions the public
key into the installer image for distribution to customers.

1. In a secure SINVO-admin workstation with cryptography installed, run
   `python3 ci/bootstrap-signing.py /secure/offline/sinvo-signing-staging`.
   Output files include the private Jenkins credential text (keep secret),
   public server base64 key, and public BackOffice raw key.
2. SINVO Jenkins administrator creates Secret Text credential
   `sinvo-staging-signing-key` with contents of the private text file.
3. SINVO Update Server administrator configures environment
   `SINVO_SIGNING_KEY_ID=staging-1`,
   `SINVO_SIGNING_PUBLIC_KEY=<contents of public server b64>`,
   `SINVO_REQUIRE_SIGNATURES=1`.
   Back up and protect the Update Server config. Avoid printing secrets.
4. SINVO includes the public raw key in the trusted initial installer image.
   During trusted initial installation, as root call
   `bash deploy/rocky/provision-trust.sh /path/in/installer/public.raw`.
   It installs a root-owned /etc/pos-erp/sinvo-signing-public.raw and refuses
   to replace an existing mismatched key. Neither web UI nor Update Server
   controls that path. No customer action is necessary after installation.
5. BackOffice updater automatically loads the pinned public key and requires
   a valid Ed25519 signature before an archive is ever eligible to install.

The Staging Jenkins pipeline now REQUIRES the publisher secret and fails
closed rather than silently releasing unsigned packages. Until SINVO
completes bootstrap and configures Jenkins/Update Server, publishing will
intentionally fail. Tests still run.

Do not commit or distribute the private signing seed. Key rotation requires
an authenticated, separately controlled trust-anchor update; it is not safe
to silently replace the pinned public key from an update response.

These changes provision signing trust but DO NOT activate unattended package
extraction, database migrations, symlink flips, or service restarts.
