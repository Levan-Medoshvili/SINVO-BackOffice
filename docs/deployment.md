# ERP deployment: 10.0.110.151

The root Jenkinsfile deploys the trusted **Production** branch to the Rocky Linux 9 server. It uses the existing **pos_server_creds** Jenkins username/password credential, shown as `root` in the supplied configuration. The password is read by SSH through an askpass helper and never inserted into a command argument, git file, archive or log.

## Jenkins requirements

Use a Linux Jenkins agent with Bash, Git, OpenSSH (`ssh`, `scp`, `ssh-keygen`), tar and sha256sum. OpenSSH must support `SSH_ASKPASS_REQUIRE=force` and `StrictHostKeyChecking=accept-new`. Jenkins needs Pipeline, Git and Credentials Binding; the configured SCM checkout must have access to this private repository. No SSH Pipeline Steps/sshpass plugin is needed.

Configure Pipeline from SCM to branch `*/Production`, script path `Jenkinsfile`, or use a multibranch job discovering Production. The existing webhook delivers pushes; its Jenkins job still controls which branch it builds. Other branches archive source and never receive the server credential. Keep production credentials unavailable to untrusted PR jobs and use a trusted build agent.

The pipeline defaults are:

| Parameter | Default | Purpose |
| --- | --- | --- |
| `TARGET_HOST` | `10.0.110.151` | ERP server SSH address |
| `DB_ENGINE` | `postgres` | PostgreSQL, MySQL or MSSQL |
| `HTTP_ALLOWED_CIDRS` | `10.0.0.0/8` | Networks allowed into this private HTTP pilot |

Preinstall the server's console-verified SSH host key in the Jenkins OS user's persistent `~/.ssh/known_hosts` when possible. Without an existing key, the first connection uses trust on first use and stores it there. Subsequent changed keys are rejected. That first connection does not independently authenticate a previously unknown host key; restrict it to your trusted management network. Do not delete a changed-key warning without checking the server fingerprint.

## What the first deployment does

1. Archives the exact checked-out Production revision and verifies its SHA-256 after upload.
2. Installs build libraries, Nginx and selected database-client dependencies. Python 3.14.8 is built under `/opt/pos-erp-python/`, with a pinned source digest and checks for SSL/SQLite/ctypes. Rocky's system Python remains in place.
3. Creates unprivileged service/build accounts, data directories, systemd configuration and the Nginx site.
4. On a fresh default installation, installs PostgreSQL 16, creates a dedicated ERP database/login, and a separate disposable CI database/login. Existing different-major PostgreSQL data and conflicting database names cause a stop for review.
5. Generates application/database secrets and a first-start installation key in root-owned mode-600 files under `/etc/pos-erp`. Existing configuration and passwords are preserved.
6. Installs the selected Python requirements into the release virtual environment as an unprivileged build user. The application itself runs as `simplepos`.
7. Checks migrations and runs backend tests against the separate CI database, including real database locking tests.
8. Stops central application writes, creates and checks a PostgreSQL backup, applies migrations, collects static assets, switches the release and starts Gunicorn/Nginx. New installations create the administrator through browser setup.
9. Verifies the database health response, exact deployed commit, Nginx proxy and custom sign-in/setup page before reporting success.

The first run can take longer while Python compiles. Package download, DNS, SSH or CI failures stop the deployment. A failed migration keeps the service stopped for diagnosis; the pipeline does not roll a database back over new data.

## Access after a successful build

- BackOffice: **http://10.0.110.151/**
- Health/version: **http://10.0.110.151/healthz/**
- Cashier server address: **http://10.0.110.151**

For a new installation, retrieve the setup key on the server:

```bash
sudo cat /etc/pos-erp/setup.env
```

For a new installation, enter the `SIMPLEPOS_SETUP_TOKEN` value on the setup unlock page. Then enter Company Name (ENG), Company Name (GEO), Admin Email, Admin Username, Password and its confirmation. Company address/phone and administrator first/last names are optional. Setup creates one company and the administrator atomically; it cannot be claimed again. Sign in with those credentials and create branches, products and employee accounts. Keep the installation key out of Jenkins logs and GitHub.

When upgrading an existing pilot that already has a company and active superuser, the migration marks setup complete and preserves all accounts and business data. Use the existing administrator credentials; if it was the original deployment-generated account, its original credentials are still in `/etc/pos-erp/initial-admin.env`. Complete the company details in **Company settings**. A database containing more than one company is rejected before applying the single-company constraint; it must be split deliberately, with no automatic deletion.

`/admin/` now redirects to the custom BackOffice. Django's default model-editing pages are no longer routed. The deployment no longer calls `bootstrap_admin` or generates a new administrator password.

For a different administrator or password recovery, use the interactive wrapper:

```bash
sudo pos-erp-manage createsuperuser
sudo pos-erp-manage changepassword admin
```

Sample inventory is optional: `sudo pos-erp-manage seed_pilot`. It is not inserted automatically into a new business database. See [employee and cashier setup](cashier-access-and-installation.md).

This initial endpoint uses HTTP on the allowed private network. Cashier must explicitly allow private-LAN HTTP. Add a hostname/certificate and a reviewed HTTPS Nginx configuration before exposing it beyond the lab. The automatic LAN renderer deliberately refuses to overwrite an existing HTTPS application configuration.

## Repeat deployments, databases and recovery

Runtime: `/opt/pos-erp/current/backend`; immutable releases: `/opt/pos-erp/releases/<commit>`; application data: `/var/lib/pos-erp`; environment: `/etc/pos-erp/backend.env`; PostgreSQL backups: `/var/backups/pos-erp`. No application or POS data is stored inside the replaceable source checkout. Old releases/backups are retained for review; set a retention/off-server backup policy after the pilot.

For MySQL/MSSQL or externally managed PostgreSQL, prepare `backend.env` from `deploy/rocky/backend.env.example`, plus a separate `ci.env` whose `DB_NAME` ends in `_ci` and uses a different DB login with test-database create/drop permissions. Connect these to isolated disposable test databases. Install a root-owned executable `/etc/pos-erp/backup-before-deploy` that creates and verifies a real database-native backup and exits nonzero on failure. The automatic local PostgreSQL provisioning is only for the fresh default installation. Selecting another `DB_ENGINE` does not migrate existing data. Choosing MSSQL installs Microsoft ODBC Driver 18 and accepts its driver EULA.

Diagnostics:

```bash
sudo systemctl status pos-erp nginx postgresql
sudo journalctl -u pos-erp -n 100 --no-pager
sudo nginx -t
curl -f http://127.0.0.1:8000/healthz/
curl -f -H 'Host: 10.0.110.151' http://127.0.0.1/healthz/
```

SELinux remains enabled; the deployment permits Nginx's network proxy connection. If firewalld is running, the pipeline adds HTTP rules only for the configured private CIDRs. It does not expose the database or Gunicorn listener. Network/VLAN firewalls still need the intended client route to the server.

After a failed migration, inspect its log and the saved backup before restarting or restoring anything. Code rollback requires schema compatibility. Restore a database only through a reviewed database-native recovery procedure; never replace a POS database that has pending sales.

## Validation boundaries

Local migration checks, backend tests, Cashier tests and the cross-repository HTTP test verify the split. The Production pipeline repeats backend tests on the selected real database and checks server health before success. A GitHub push alone is not evidence that Jenkins completed: inspect the build result and `build_revision` in `/healthz/`.

Reference: [PostgreSQL on the Red Hat family](https://www.postgresql.org/download/linux/redhat/), [OpenSSH host-key policy](https://man.openbsd.org/ssh_config), [Python 3.14.8 release](https://www.python.org/downloads/release/python-3148/).
