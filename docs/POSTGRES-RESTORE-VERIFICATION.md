# SINVO BackOffice: PostgreSQL restore verification

Use only on an authorized development/test server. This is a root-only,
explicitly invoked maintenance command; neither Gunicorn nor the 15-minute
enrollment timer calls it.

```bash
python3 backend/sinvo_postgres_verify.py \
  --database simplepos_erp --directory /var/backups/pos-erp
```

Requirements: local PostgreSQL managed by the host, `runuser`, `pg_dump`,
`pg_restore`, `psql`, `createdb`, `dropdb`, and a root-owned mode-0700
backup directory. The PostgreSQL `postgres` OS account must be able to
connect to the source database and create/drop a temporary database.

The script:
- Acquires a host-local exclusive verification lock.
- Streams pg_dump (as postgres) into a root-owned mode-0600 file.
- Validates archive readability and saves its SHA-256.
- Creates a fresh randomly named `sinvo_verify_*` database.
- Restores the archive there with `--exit-on-error`, without owner/ACL data.
- Compares restored public base-table count with source count.
- Drops only the verification database it successfully created.
- Retains the backup and checksum for recovery reference.

A database may change during a live pg_dump and subsequent source-table
count comparison; consider writes and maintenance mode for authoritative
validation. Table count is a basic smoke test, not row-by-row verification.
This does not establish that future migrations can be reversed.
The independent installation feature remains DISABLED pending signature
verification, schema-aware recovery, and health-gated activation.

If the temporary database cannot be removed, the command fails loudly and
prints its name for manual examination. Never use it with a customer-chosen
source database name matching `sinvo_verify_*`.
