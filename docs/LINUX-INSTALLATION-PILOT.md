# SINVO Linux installation pilot

The Linux installer identifies the operating system and selects a validated
installation adapter. **Currently only Rocky Linux 9 is enabled.** AlmaLinux,
RHEL, CentOS Stream, Ubuntu, Debian and others are detected but blocked until
their package/database/service adapters pass dedicated clean-VM validation.

This is a clean-VM Staging pilot only, not yet the commercial one-click
customer installer, and not a cross-OS automatic migration tool.

From a trusted, clean **Staging** checkout on a new Rocky Linux 9 VM:

```bash
sudo bash deploy/rocky/install-linux.sh --detect
sudo bash deploy/rocky/install-linux.sh --plan --ip 10.0.110.160 --allow-cidrs 10.0.110.0/24
sudo bash deploy/rocky/install-linux.sh --install --ip 10.0.110.160 --allow-cidrs 10.0.110.0/24 --confirm-new-vm
```

The installer refuses an existing BackOffice installation/configuration,
a populated release directory, or an existing local PostgreSQL cluster.
It requires a clean Git checkout and private-network settings, then delegates
to the proven Rocky `deploy.sh` pipeline to provision OS packages, managed
PostgreSQL and isolated CI credentials, Python, tests, migrations, service,
Nginx and final health checks.

**No source trust is conferred by the local source checksum.** For commercial
customer installation, a separately signed immutable installer release and
bundled publisher public key will be mandatory; Staging source checkout
is not an authenticated installer distribution channel.

**No trusted public key is automatically fetched from the Update Server**.
The existing signing public key must be bundled by SINVO with the eventual
signed commercial installer. The current pilot deliberately does not
provision a missing key from an untrusted network location.

Do not run on `10.0.110.151` or other existing BackOffice servers.
Run on the new disposable VM only. HTTP access is limited to RFC1918 LAN
networks; enable properly configured TLS before external use.
