# SINVO first-install LAN HTTPS setup (preview only)

The Staging setup wizard is now reachable directly from another workstation
using the new VM's internal IPv4 address. It is **not yet an installer**:
field validation is implemented, but no dependencies, PostgreSQL, database
connectivity checks or BackOffice releases are installed.

## Start on a new Rocky Linux 9 VM

```bash
sudo dnf install -y openssl
git clone --branch Staging https://github.com/Levan-Medoshvili/SINVO-BackOffice.git
cd SINVO-BackOffice
python3 deploy/rocky/setup_wizard.py --ip YOUR_VM_LAN_IP
```

The server prints a URL like `https://10.0.110.160:8765/?token=...`.
Open that **exact URL** from a workstation in the same trusted LAN.

The HTTPS certificate is ephemeral and **self-signed**; browser trust warnings
are expected. For this first test, **enter only dummy passwords**: without a
trusted certificate, a network attacker could impersonate the setup page.
Commercial installation must support a provisioned CA certificate, DNS-validated
certificate or independently verifiable certificate fingerprint.

If firewalld blocks access, authorize only your administrator computer IP
temporarily (substitute its actual /32 host address):

```bash
sudo firewall-cmd --add-rich-rule='rule family="ipv4" source address="10.0.110.100/32" port protocol="tcp" port="8765" accept'
```

The rule is *runtime-only*, not permanent; remove after testing:

```bash
sudo firewall-cmd --remove-rich-rule='rule family="ipv4" source address="10.0.110.100/32" port protocol="tcp" port="8765" accept'
```

The wizard listens only on the chosen VM private IPv4 address, requires a
random URL token, never logs form details, and automatically stops after
30 minutes. It requires openssl to generate a one-day temporary SAN certificate
in an automatically removed private directory.

Remote PostgreSQL/MySQL/MSSQL connection tests, secure persistent installation
secrets, signed Update Server downloading and deployment remain to be built.

The proposed default database name is `sinvo-erp`. The current Rocky Linux deployment scripts still provision `simplepos_erp`; the full installer must update those scripts before enabling deployment of this configured database name. Hyphens in PostgreSQL database identifiers require proper SQL identifier quoting.
