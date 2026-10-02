# RS authentication and invoice boundaries

Reviewed 2026-10-01 from the owner-supplied documents. These are proposed integration boundaries, not implemented endpoints.

## Three separate interfaces

| Interface | Source | Purpose and credentials |
| --- | --- | --- |
| Waybill SOAP | `waybill_protocol.pdf`, v4.0.4 | Incoming/outgoing consignment notes; integration service user `su` and `sp` |
| Invoice SOAP | `invoice-protocol.pdf`, v3.0.6, 2026-06-24 | Tax invoices, corrections and advance allocations; method-specific IDs plus service credentials |
| RS open authorization | `RSoAuth.html`, v1.0.1, “Rs oAuth v3” | Identify an authorized taxpayer through an RS login callback and server-side exchange |

The OAuth document does **not** describe obtaining a bearer/refresh token for the waybill or invoice SOAP APIs. Do not replace their service-user authentication with an assumed OAuth flow.

## Open authorization flow

The document requires an application registration in the RS portal to obtain a PublicKey and SecretKey. Its client example uses the RS-provided login component and callback. On success, the browser passes `AuthKey` to our backend; only the backend exchanges that code with `https://eservices.rs.ge/WebServices/oAuth.ashx` using the application's SecretKey.

`AuthKey` is single-use and expires three minutes after generation. The response is XML with `Authenticated`, `FullName`, `PersNo`, `PayerType` and `Address`. The negative example contains `Authenticated=false` only. Parse missing fields accordingly. A taxpayer identity is not permission to join an arbitrary SimplePOS tenant: verify the active enrollment session and company relationship separately.

Keep SecretKey and service passwords in server-side secret storage. The documented exchange puts secrets in query parameters; redact complete query strings from client, reverse-proxy, tracing and error logs, and do not expose the exchange URL to Cashier or the browser. Bind the callback to the initiating authenticated session and expire/reject replayed enrollment attempts. Confirm additional RS callback-origin and session-binding requirements during application registration; they are not specified in the supplied example.

No application keys were provided, so no OAuth authorization attempt was performed.

## Invoice scope

The invoice protocol names `https://www.revenue.mof.ge/ntosservice/ntosservice.asmx`. Verify its deployed operation contract before implementation. Its 2026 changes include advance-invoice attachment/allocation methods (v3.0.5, May 6) and `change_barter_status` (v3.0.6, June 24). These operations belong in a separate accounting integration with explicit permissions and audit history.

`get_user_invoices` returns documents where the authenticated taxpayer is buyer or seller and which changed during the requested interval. It documents second precision, a maximum three-day window, and service credentials plus `user_id` and `un_id`. Validate those IDs against the authenticated company.

The documented list columns are:

| Group | Exact fields |
| --- | --- |
| Identity and parties | `Id`, `seller_un_id`, `buyer_un_id`, `saident_no_s`, `org_name_s`, `saident_no_b`, `org_name_b` |
| Status and correction | `status`, `was_ref`, `k_id` |
| Number and dates | `f_series`, `f_number`, `reg_dt`, `operation_dt`, `last_update_date` |
| Rejection | `ref_s_user_id`, `ref_date` |
| Agreement | `agree_date`, `agree_s_user_id` |
| Other | `s_user_id`, `tanxa`, `notes` |

The document describes `tanxa` as the total rounded to four decimal places. Use Decimal and preserve source precision; format retail receipts separately. `notes` is described as the buyer's shop number, not a reliable SimplePOS branch ID without an explicit mapping. These list fields are not the complete invoice-detail schema.

An invoice and a waybill are separate external document identities. Receiving stock from a waybill and later retrieving its invoice must not add stock twice. Keep financial status separate from receipt status, link documents explicitly, and review corrections instead of overwriting posted history.

## Test evidence and remaining access

The waybill endpoint answered read-only account-list requests made with the two documented test accounts. The first account did not pass `chek_service_user` as a service user. No integration-user password was obtained from the list, and no credentials were guessed or changed. Obtain or provision a dedicated test service user with the required permissions and IP policy before document-import tests. The public shared test accounts must never be used for production data.
