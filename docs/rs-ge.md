# RS.ge waybill field research

Reviewed 2026-10-01 against the three documents supplied by the project owner. This is a receiving-integration design; the application does not yet import live documents.

## Official sources and confidence

- Supplied `waybill_protocol.pdf`, version **4.0.4**, 42 PDF pages. Its change history includes 2024-10-03. This supersedes the earlier [public legacy protocol](https://eservices.rs.ge/Docs/el-zednadebis_protokoli.pdf), version 3.0.0.1, for this design.
- Supplied `invoice-protocol.pdf`, version **3.0.6**, dated 2026-06-24, and `RSoAuth.html`, documentation version **1.0.1**, describing “Rs oAuth v3”. These are separate interfaces; see [authentication and invoices](rs-ge-auth-and-invoices.md).
- [Current operations index](https://services.rs.ge/WayBillService/WayBillService.asmx).
- [Incoming waybill search](https://services.rs.ge/WayBillService/WayBillService.asmx?op=get_buyer_waybills_ex) and [waybill detail](https://services.rs.ge/WayBillService/WayBillService.asmx?op=get_waybill).

The operation pages expose XML results rather than a complete nested schema. The supplied PDF contains malformed sample tags and conflicting optionality descriptions, so do not copy its examples as executable XML. Compare the manifest against authorized document responses before accepting a production parser. Preserve unknown XML elements so additions cannot silently lose data. Source documents and their published test passwords are not committed to this repository.

Read-only service checks on 2026-10-01 reached the official HTTPS endpoint. `get_service_users` returned 94 service-user records for each of the two documented test accounts; only counts and field names were recorded. A `chek_service_user` request using the first documented account returned HTTP 200 with `false`. The protocol distinguishes portal credentials (`user_name`, `user_password`) from integration credentials (`su`, `sp`). A successful list response does not establish permission to fetch waybills. No service user was created or modified; no waybill, invoice, acknowledgement or tax operation was written. A configured test **service user and password** are still needed for the receiving smoke test.

## Identifiers

| Identifier | Proposed storage | Meaning |
| --- | --- | --- |
| `WAYBILL/ID` | ExternalWaybill.rs_waybill_id | External document identifier |
| `WAYBILL_NUMBER` | ExternalWaybill.number | Display document number; keep separately |
| `GOODS_LIST/GOODS/ID` | ExternalWaybillLine.rs_line_id | Goods record within a waybill; not the local product identity |
| `BAR_CODE` | ExternalWaybillLine.barcode | Source barcode/product code; retain exact text |
| SimplePOS product ID | Product.id | Stable local catalog identity across deliveries and locations |

Use `(company, integration account, waybill ID)` as the import identity and `(import, line ID)` for a sourced line. An import revision must remain distinguishable from a duplicate retry. A product can link to many waybill lines. Supplier-to-product mappings belong in a separate table, scoped by company and supplier. Do not put a single overwriteable “RS product ID” on Product.

## Fields to preserve

The machine-readable [mapping manifest](../shared/contracts/rs-ge-fields.json) lists exact XML keys and proposed internal names. Version 2 adds `CATEGORY`, `IS_MED`, `CUST_STATUS`, `CUST_NAME`, `IS_CONFIRMED`, line-level `W_ID` and `WOOD_LABEL`, and nested timber-document fields. These preserve specialized source information even when a supermarket does not use it. `CATEGORY` is the RS document category, separate from SimplePOS product categories. The obsolete document-level `WOOD_LABELS` example is retained only if encountered in raw source; current timber labels belong to goods lines.

Preserve the source XML document (not a SOAP envelope containing credentials) with a content hash, retrieval time, account identity, parser version and access controls. Source data, operator mappings and local quantity corrections are separate. Store both original date strings and normalized instants after validating the service time-zone convention. Amounts and quantities use Decimal; IDs and codes cross API boundaries as strings. Null/missing values stay distinct from zero.

Fetch unit, waybill-type, transport-type, excise and error reference lists through the documented service operations instead of treating demo labels as permanent enumerations. Keep wire spelling such as `SELER_UN_ID`, `CHEK_BUYER_TIN` and `TRANSPORT_COAST` inside the adapter; use clear internal names elsewhere.

The protocol says `UNIT_TXT` is required when `UNIT_ID=99` (other). For medicine waybills, `BAR_CODE` holds the medicine registration number: do not assume every source value is a scanner barcode. Incoming-list `IS_CONFIRMED` is 0 unconfirmed, 1 confirmed, -1 rejected, independent of transport/document `STATUS`. Treat unfamiliar codes as reviewable source values.

The PDF is inconsistent about whether `QUANTITY_EXT` is required. Treat it as optional in the staging manifest and confirm the rule against the chosen operation/version before posting externally. Legacy `VAT_TYPE` values are 0 ordinary, 1 zero, 2 exempt; preserve them as source classifications, not a hardcoded retail tax rate. Use validated company tax configuration for checkout.

## Receiving workflow

1. A backend worker retrieves incoming documents using the company's service credentials. Cashiers never receive these credentials.
2. Stage list metadata and detail XML. Repeated refreshes update a revision or recognize identical content; they do not add stock.
3. An employee selects the receiving branch stock location or warehouse, resolves supplier/product/unit mappings and checks actual quantities and cost.
4. Post the local receipt and stock movements atomically, with permissions and idempotency checks. A discrepancy needs a recorded reason. Supplier cost and retail price remain independent.
5. If required, handle RS.ge acknowledgement as an explicit, separately audited action. Local receipt state and external document status remain separate.

Returned status codes and correction workflows must be checked using real authorized fixtures. Preserve unrecognized values and display a review state instead of guessing. Reject unsafe XML constructs, limit input size and nesting, redact credentials from logs, and restrict raw documents to authorized company users.

## Finding changes after initial import

`get_waybills_v1(su, sp, buyer_tin, last_update_date_s, last_update_date_e)` searches by last-change time, with second precision and a maximum **three-day interval**. The v4.0.4 history and method description say results can include both incoming and outgoing documents involving the authenticated company. Do not treat every returned document as a receipt. Check direction/ownership against the integration account, fetch the relevant detail, and retain corrections to previously seen IDs.

Use bounded, overlapping windows and deduplicate by document identity and revision hash. Commit a window cursor only after all results and details are durably staged. On outage recovery, split the missed period into windows of at most three days. The service's time-zone and boundary inclusion rules still need validation; store raw date text and avoid deriving a UTC convention from sample dates alone. The documented v1 result has no complete field table, so an invented `LAST_UPDATE_DATE` header is not added to the manifest.

## Next test with a configured service user

1. Authenticate with `chek_service_user`, checking its boolean result rather than HTTP status alone.
2. Retrieve unit/type/transport reference lists; retain IDs exactly as returned.
3. Query a short test period, distinguish incoming/outgoing records, and fetch one test waybill.
4. Save a sanitized fixture with synthetic parties/addresses and preserved XML structure; check the new fields and absent/empty values.
5. Stage the same document twice and verify one import identity and no stock changes. Post a reviewed local test receipt twice and verify only one set of stock movements.

These steps must use a test company and local test database. Keep external confirmation, activation, deletion and invoicing outside the read-only smoke test.
