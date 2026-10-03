# Future subscription and VM provisioning service

Status: architecture boundary only. This release does not charge cards, reconcile bank transfers, enforce subscriptions, shut down VMs, or delete customer data.

One customer company receives one isolated VM, ERP database, installation identity and backup namespace. The storefront/control service runs separately and stays available when a customer's ERP VM is suspended. Customer ERP users never receive hypervisor, billing-provider or other customers' credentials.

The storefront will register a company, record billing contacts, choose a plan (for example BackOffice plus 50 active branches), collect a provider-managed card payment method or assign bank-transfer instructions, and expose Cashier/ISO downloads. An order becomes paid only after a verified provider event or a reconciled received bank transaction. Persist an idempotency key for payment events, bank transactions and provisioning jobs so retries cannot charge or deploy twice. Do not store raw card details in the ERP.

Provisioning creates the VM from a versioned image, database, TLS hostname, unique secrets and a one-use first-start claim. Mark the workspace ready only after health checks. The customer then enters the required English/Georgian company names and administrator information through the existing setup form. The current manual setup key can later be replaced by a scoped, expiring claim issued through the portal.

The planned lifecycle is: awaiting payment → provisioning → active → payment overdue → suspended → deletion eligible → deleted. A configurable grace period and reminders precede suspension. The infrastructure controller records VM power state and desired subscription state separately, with an audit trail and retry-safe jobs. Plan limits such as active branches must be checked server-side when they are introduced.

On suspension, shut down the company VM after an application-aware maintenance process. Retain it for the operator-configured period (initial candidates: one or two months). Payment received before deletion cancels pending deletion, starts the same VM and verifies health; it must not create a replacement database. Immediately before permanent deletion, recheck payment/subscription state and the retention deadline under a lifecycle lock. Require a recorded deletion policy, backup retention decision and operator-visible audit event. Never let a stale queued job delete a reactivated VM.

VM shutdown alone does not stop offline Cashiers. The future entitlement policy must define a bounded signed offline validity period, preserve unsynchronized sales and avoid interrupting a payment or destroying an outbox. That decision is not implemented by this release. Likewise, a future appliance ISO is a packaging target for the same Cashier code; no ISO is built yet.
