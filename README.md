# SimplePOS ERP

BackOffice and shared API for the SimplePOS supermarket system. The desktop application lives in [pos-cashier](https://github.com/Levan-Medoshvili/pos-cashier).

## Deploy and sign in

The `Production` branch deploys through Jenkins to **10.0.110.151**, using the existing username/password credential **pos_server_creds**. The pipeline installs the Rocky Linux 9 packages, builds Python 3.14.8, sets up PostgreSQL 16 on a fresh server, runs backend tests on a separate database, backs up the application database, migrates and verifies Nginx/Gunicorn health.

After Jenkins completes successfully, open **http://10.0.110.151/admin/** from the permitted private network. Initial credentials are generated on the server; read `/etc/pos-erp/initial-admin.env` as root and change the password after signing in. The pipeline never prints that password.

See [deployment and recovery](docs/deployment.md), [cashier access](docs/cashier-access-and-installation.md) and [migration provenance](MIGRATION.md).

## Implemented

- Companies, branches, warehouses, categories, products, price history, stock adjustments and sales.
- Employee access: Backend/Cashier/Both, branch restrictions, company groups and direct permissions.
- Cashier enrollment, bounded offline authorization, branch catalog and idempotent sale ingestion.
- Scoped live checkout supervision with POS-confirmed item removal.
- Configurable PostgreSQL/MySQL/MSSQL drivers and signed Cashier release delivery.

This is a cash-only, non-fiscal pilot. Bank/fiscal integration, subscriptions, receiving/imports, media campaigns and scheduled application updates remain planned.

## Layout

- `backend/`: Django `config`, `users`, `commerce`, migrations and tests.
- `deploy/rocky/`: package installation, database provisioning, service and deployment scripts.
- `ci/`: Jenkins SSH transport.
- `shared/contracts/`: Cashier API and RS.ge field contracts.
- `docs/`: deployment, architecture and integration research.

The API remains compatible with Cashier v0.2. Marketing names can change through `SIMPLEPOS_BRAND`; database labels and installation identities remain stable.

## Local development

```bash
python3.14 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
export SIMPLEPOS_SECRET_KEY=development-only-change-this-key-more-than-fifty-characters
export SIMPLEPOS_DEBUG=1 SIMPLEPOS_ALLOW_SQLITE=1 DB_ENGINE=sqlite
mkdir -p backend/var
.venv/bin/python backend/manage.py migrate
.venv/bin/python backend/manage.py createsuperuser
.venv/bin/python backend/manage.py runserver 127.0.0.1:8000
```

Run `manage.py test commerce` with the same environment. For the real HTTP cross-repository test, clone `pos-cashier` alongside this checkout and run `.venv/bin/python tools/test_checkout_e2e.py` with Node 24 installed. `CASHIER_SOURCE_DIR` can specify another Cashier checkout path.
