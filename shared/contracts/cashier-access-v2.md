# Cashier access and live basket protocol v2

These endpoints extend the existing catalog/cash-sale API; catalog `api_version` remains 1. Use HTTPS. Company identity always comes from the authenticated employee/device. One local database belongs to one installation/register.

## POST /api/v1/cashier/sign-in/

```json
{
  "username": "cashier-1",
  "password": "entered-by-employee",
  "branch_name": "BRANCH-01",
  "branch_address": "Optional enrollment hint",
  "installation_id": "persistent-installation-uuid",
  "installation_secret": "persistent-random-32-byte-secret-encoded-as-hex"
}
```

The device creates and encrypts its installation identity before its first request. The employee must be active, belong to an active company, have Cashier/Both access and be allowed in the requested active branch. The branch is matched by case-insensitive name or exact code within that company; ambiguity fails. Address is only a hint. The first valid request creates one register, serialized at the branch. Subsequent calls validate the same installation secret and register/branch binding. Existing v0.1 devices include their old Bearer credential to bind that register rather than create another. After enrollment, installation identity handles retries even if an earlier response rotated the Bearer token and was lost.

Successful response contains `register_credential`, `branch`, `register` and `operator`. Operator fields are `session_id`, `user_id`, `username`, `name`, `company_id`, `branch_id`, `register_id`, `permissions`, `issued_at`, `expires_at`, and signed `authorization`. Persist the rotated device credential before catalog download. Never expose it, the installation secret, password verifier or signed grant to the renderer/customer window.

Application/branch denial returns 403; malformed input returns 400. Fixed five-minute rate buckets allow 10 attempts per normalized username and 100 per source IP; excess returns 429. An explicit online denial must not trigger offline fallback. The client permits cached sign-in only on connectivity failures or HTTP 502/503/504, using an encrypted scrypt verifier and unexpired server authorization. Five wrong offline attempts impose a five-minute local delay. Sessions last `SIMPLEPOS_OFFLINE_LOGIN_DAYS` (1–30, default 7); the heartbeat refreshes permissions without extending that expiry.

## POST /api/v1/basket/sync/

Bearer-authenticated device heartbeat, approximately every two seconds. Send the current snapshot and up to 100 stored command results:

```json
{
  "basket": {
    "id": "basket-uuid",
    "revision": 14,
    "owner": "cashier-user-id",
    "state": "active",
    "authorization": "signed-operator-authorization",
    "lines": [{
      "key": "product-uuid:price-uuid",
      "id": "product-uuid",
      "price_id": "price-uuid",
      "quantity_milli": 2000,
      "price_minor": 450
    }]
  },
  "acknowledgements": [{
    "id": "command-uuid",
    "status": "applied",
    "detail": "Removed before payment by supervisor request."
  }]
}
```

States are `empty`, `active`, `locked` and `completed`. At most 250 lines; product/price/location/quantity are validated centrally and display names come from the server. The `owner` field is local recovery metadata; the backend derives the operator from the signed authorization. Empty/completed snapshots contain no lines. A locked snapshot has no active authorization. Revision is a persisted monotonic counter across baskets and sign-ins; New sale also changes the basket UUID. An older revision, or a different basket UUID at the same revision, returns 409. Retain the local database and investigate this conflict instead of resetting it.

Response fields:

| Field | Meaning |
| --- | --- |
| `commands` | Pending commands, up to 20; each has `id`, `basket_id`, `expected_revision`, `line_key`, `reason`, `manager_name`, `expires_at` |
| `acknowledged` | Command IDs whose result the server has durably recorded |
| `operator` | Current policy for this session, or null |
| `access_denied` | Lock the current session and remove its offline cache when true |

Supervisors use a CSRF-protected BackOffice POST, scoped by company and permitted branches, to request removal. A request requires an active snapshot at most 15 seconds old, an exact basket/revision/line, a 3–250 character reason and no other unexpired pending command for the register. Commands expire after 90 seconds.

The POS removes only from that exact current unpaid, unlocked basket while the command/session are valid. Basket removal, new revision, notice and command result commit in one local SQLite transaction. Store rejected results too. Duplicate command IDs replay the original result without another removal. Keep results pending until the server acknowledges them. A delayed acknowledgment can record an application that occurred before the server marked delivery expired; server expiry alone does not prove the POS never applied it. The management UI must show pending, applied, rejected or expired accurately. An applied command never edits a completed sale.

## Lock and revoke

The desktop's **Sign out** locks locally, keeps the bounded offline cache, and preserves the unfinished basket's owner. Starting the application also requires login. Another user cannot take an unfinished basket over.

`POST /api/v1/cashier/sign-out/` with Bearer credential and `{ "authorization": "signed-grant" }` explicitly ends that server session. It is a revocation endpoint, not the desktop's routine local lock. A device using it should also clear its cached grant. Historical completed sales keep their original authorization for delayed synchronization. Current user/branch permission changes are checked again online; an offline device cannot learn a revocation immediately.

See [cash sale contract](checkout-v1.md) for grant timing and migration behavior, and [installation](../../docs/cashier-access-and-installation.md) for the signed first-download feed.
