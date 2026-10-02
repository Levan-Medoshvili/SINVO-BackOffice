# Repository split verification

- ERP: 30 tests run on SQLite; 29 passed and one row-lock concurrency test was skipped. No missing model migrations.
- Cashier: all 20 Node tests passed, including signed bootstrap downloads and offline cached launch.
- Cross-repository HTTP integration passed: enrollment, offline login, supervisor removal, local restart, and a lost acknowledgment produce one sale and one stock deduction.
- Deployment shell scripts passed Bash syntax checks; Python files compiled. Documentation links were checked.

The local backend checks used Python 3.12. The Production pipeline installs the pinned Python 3.14.8 with ctypes/SSL checks, then reruns ERP tests against the selected real database before migrations and release activation. Live Rocky/Jenkins execution is a separate deployment result; a successful source push does not prove server health. Native Windows/USB/bank/fiscal validation remains pending.
