# Cash checkout contract v1

Catalog, sales and basket requests use `Authorization: Bearer <register UUID>.<random secret>` over HTTPS. Cashier v0.2 obtains a rotated credential through [employee sign-in and enrollment](cashier-access-v2.md); an administrator can also issue/rotate it for recovery. Only its SHA-256 hash is stored centrally. Cashier encrypts the credential through OS credential storage. Credential revocation blocks the next online request; it cannot instantly stop an offline device.

## GET /api/v1/catalog/

Returns `api_version: 1`, `generated_at`, `brand`, `company`, `branch`, `register` and `products`. Identity comes from the register credential, never a client-selected company ID. Products are limited to active products enabled at that branch. Each includes `id`, `barcode`, `name`, `name_ka`, `category`, `category_ka`, `unit`, `price_minor`, `price_id`.

Money is integer tetri. Quantities are integer thousandths of the product's unit. `1000` is one piece or one kilogram; fractional pieces are rejected. Line totals use half-up rounding once: `(price_minor * quantity_milli + 500) // 1000`.

A product requires an initial branch/warehouse. Assignments permit additional locations. Opening stock and corrections are posted as signed movements. Product units, company ownership, stock assignment identity and register location cannot be rewritten after creation.

The pilot downloads a full catalog on enrollment and successful synchronization. It polls every 60 seconds and supports manual synchronization. It has company-wide product prices; scoped scheduled prices and push notifications remain planned. Existing basket lines retain their price revision. Historical published prices remain acceptable for delayed offline cash sales. In v0.2, completion must occur during the cashier's bounded session (seven days by default), and delayed upload is allowed through 30 days after its expiry.

## POST /api/v1/sales/

```json
{
  "sales": [{
    "id": "client-generated-uuid",
    "cashier_authorization": "signed-operator-authorization-from-sign-in",
    "occurred_at": "2026-10-01T18:00:00+04:00",
    "currency": "GEL",
    "payment_method": "cash",
    "cash_received_minor": 1000,
    "total_minor": 900,
    "lines": [{
      "product_id": "product-uuid",
      "price_id": "published-price-uuid",
      "quantity_milli": 2000,
      "unit_price_minor": 450,
      "total_minor": 900
    }]
  }]
}
```

1–100 sales per request, 1–250 product/price lines per sale. Do not change a completed sale's payload when retrying. Local completion and outbox insertion happen in one SQLite transaction with WAL and synchronous FULL. Receipt handover is durable too; New sale explicitly releases it.

HTTP 200 contains per-sale `results`: `acknowledged` (with `server_id` and `duplicate`), `rejected`, or `conflict` (with `detail`). An identical register/client ID/payload returns the prior acknowledgment; changed content under the same ID is a conflict. A malformed batch is HTTP 400; invalid/revoked credentials are HTTP 401. Network/server failures leave pending entries intact. A 200 response alone never clears the entire queue.

New v0.2 sales require the signed cashier authorization, bound to user/session/register/branch/company. The backend checks the occurrence time against the recorded session; it keeps historical cashier identity even if current access subsequently changes. Five minutes of clock tolerance apply at the session start, revocation boundary and future-time check. Identical already-accepted retries are acknowledged before checking authorization age. `SIMPLEPOS_ALLOW_LEGACY_SALES=1` is an explicit, temporary migration option for draining unchanged v0.1 queues; it defaults off. Do not fabricate cashier identity or change an existing queued payload during migration.

Each central sale, line, stock deduction and movement is committed atomically. Register and stock rows are locked in a stable order on supported server databases. Negative central stock is retained for review because a physically completed offline cash sale must remain recorded. Archived products and disabled assignments can still receive historical sales if the assignment exists.

The pilot preserves rejected sales and shows a review count; the support-resolution UI remains to be built. Do not delete or edit outbox rows to hide errors. It uploads up to 100 oldest pending records per synchronization cycle; rejected rows are retried and can eventually block that batch, which requires administrator investigation in this pilot.

## Health

`GET /healthz/` checks the database and returns `{ "status": "ok", "api_version": 1 }`; unavailable databases return HTTP 503. It exposes no credentials or sale details.
