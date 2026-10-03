# v0.3 verification — 2026-10-03

- Backend: 42 tests run with Django 6.1.1 on Python 3.14.7 and SQLite; 41 passed, one row-lock concurrency test skipped. No missing migrations. The deployed runtime remains pinned to Python 3.14.8.
- Cashier: all 24 tests passed in Node 24 and Electron 44.5.1, including signed Linux fixture downloads, preserved local preferences, tampering/downgrade rejection and idle-only update handoff.
- Cross-repository HTTP integration passed: a pending POS cannot log in; approval and pairing-code paths both sign in and fetch the correct catalog; a legacy device upgrades; supervisor removal is acknowledged; offline restart and a lost acknowledgment produce one sale and one stock deduction.
- Browser checks passed at 360, 768, 1280 and 1600 pixels in English/Georgian: actual first-start setup/login, branch and product creation, code generation, management screens, Cashier request/code fields, waiting approval, login and Preferences. BackOffice and Cashier had no page-level horizontal overflow or JavaScript errors in these checks. Main labels are translated; some helper and validation text remains English.
- Windows x64 ZIP built. Archive integrity and Windows executable header checked. All 11 bundled source files match the working source; packaged version is 0.3.0. Electron-builder normalizes package.json, so its relevant metadata is checked separately.
- Shell deployment scripts passed Bash syntax checks. The Production pipeline reruns backend tests against the selected real database before migrations and release activation.

A source push is not proof of live deployment. Verify Jenkins and the exact build revision in /healthz/. Native Windows update/restart, real payment/printer devices, database concurrency on the selected service, and branch-targeted scheduled updates are not validated by the local fixture tests. A standalone ZIP needs trusted-starter/feed configuration before in-app signed updates are usable.
