# Shared contracts

This directory contains cross-application contracts and design specifications. Files here are not automatically loaded by Django or the Cashier.

- [Cash checkout v1](checkout-v1.md): implemented catalog, money/quantity units, cash sales and retry rules.
- [Cashier access v2](cashier-access-v2.md): implemented employee/device enrollment, offline authorization and confirmed supervisor commands.

`rs-ge-fields.json` maps documented external XML fields to proposed internal names. It is a mapping manifest, **not** an XSD, a complete live-service schema, or a database migration. Keep its wire names unchanged, including RS.ge spellings. See [research and limitations](../../docs/rs-ge.md).

Generated OpenAPI remains a future addition. Cashier synchronization must have explicit payload versions and remain compatible with older terminals during staged upgrades. Python models are private to the backend; do not import them into the Cashier.
