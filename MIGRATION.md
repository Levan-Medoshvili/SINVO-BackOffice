# Repository split

Imported from [Selio commit d26c7affd220c921a9b5ba572b4c173b5c0636c3](https://github.com/Levan-Medoshvili/Selio/commit/d26c7affd220c921a9b5ba572b4c173b5c0636c3), the completed SimplePOS v0.2 draft. This is a clean source snapshot; the original repository retains the preceding history.

ERP lives in `Levan-Medoshvili/pos-erp`; the desktop application lives in `Levan-Medoshvili/pos-cashier`. The API, cashier installation identity and local data format remain compatible.

ERP keeps the `users` and `commerce` model labels/migrations. The Django project package is now `config`. Unused legacy inventory/product/contact/dashboard apps, templates and bundled theme assets were excluded. Historical user-role model definitions remain solely to preserve that migration history; current access uses company-scoped commerce groups.

Cashier source, tests, bootstrap templates and release publisher moved to its repository root. Relative tool/test paths and its Jenkinsfile were adjusted. This source migration does not move an existing server database or a POS's local files.
