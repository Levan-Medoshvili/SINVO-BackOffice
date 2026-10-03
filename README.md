# SimplePOS ERP

BackOffice and shared API for the SimplePOS supermarket system. The desktop application lives in [pos-cashier](https://github.com/Levan-Medoshvili/pos-cashier).

## Deploy and sign in

The `Production` branch deploys through Jenkins to **10.0.110.151**, using the existing username/password credential **pos_server_creds**. The pipeline installs the Rocky Linux 9 packages, builds Python 3.14.8, sets up PostgreSQL 16 on a fresh server, runs backend tests on a separate database, backs up the application database, migrates and verifies Nginx/Gunicorn health.

After Jenkins completes successfully, open **http://10.0.110.151/**. A new installation opens first-start setup: obtain the installation key with `sudo cat /etc/pos-erp/setup.env`, then enter both company names and create your administrator. Existing installations with a company and administrator keep those accounts and open the custom sign-in page. `/admin/` redirects to the new BackOffice; the Django administration screens are disabled.

See [deployment and recovery](docs/deployment.md), [cashier access](docs/cashier-access-and-installation.md) and [migration provenance](MIGRATION.md).

## Implemented

- One company per installation, enforced by the database; no add-company page.
- Responsive BackOffice: first setup, sign-in, dashboard, branches, warehouses, categories, products, inventory, users/groups, sales and live checkouts. Mint, blue and neutral themes; English and Georgian interface labels.
- Employee access: Backend/Cashier/Both, branch restrictions, company groups and direct permissions.
- POS approval requests or ten-minute, one-use five-character pairing codes. Device authorization remains separate from employee sign-in.
- Bounded offline authorization, branch catalog and idempotent sale ingestion.
- Scoped live checkout supervision with POS-confirmed item removal.
- Configurable PostgreSQL/MySQL/MSSQL drivers and signed Cashier release delivery.

This is a cash-only, non-fiscal pilot. Bank/fiscal integration, subscriptions, receiving/imports, media campaigns and scheduled application updates remain planned.

## Layout

- `backend/`: Django `config`, `users`, `commerce`, custom `backoffice`, migrations and tests.
- `deploy/rocky/`: package installation, database provisioning, service and deployment scripts.
- `ci/`: Jenkins SSH transport.
- `shared/contracts/`: Cashier API and RS.ge field contracts.
- `docs/`: deployment, architecture and integration research.

Previously enrolled v0.2 devices retain their identity. New devices need Cashier v0.3 for the approval/code flow. Marketing names can change through `SIMPLEPOS_BRAND`; database labels and installation identities remain stable. Future subscriptions and VM provisioning belong to a [separate control service](docs/subscription-architecture.md).

## Local development

```bash
python3.14 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
export SIMPLEPOS_SECRET_KEY=development-only-change-this-key-more-than-fifty-characters
export SIMPLEPOS_DEBUG=1 SIMPLEPOS_ALLOW_SQLITE=1 DB_ENGINE=sqlite
export SIMPLEPOS_SETUP_TOKEN=development-only-setup-key-change-this
mkdir -p backend/var
.venv/bin/python backend/manage.py migrate
.venv/bin/python backend/manage.py runserver 127.0.0.1:8000
```

Open `/` and finish setup. Run `manage.py test commerce backoffice` with the same environment. For the real HTTP cross-repository test, clone `pos-cashier` alongside this checkout and run `.venv/bin/python tools/test_checkout_e2e.py` with Node 24 installed. `CASHIER_SOURCE_DIR` can specify another Cashier checkout path.

## v0.4 management

Branch checkout controls, timed notices, advertisements, named POS pairing and branch-targeted updates are described in [docs/v0.4-management.md](docs/v0.4-management.md).
