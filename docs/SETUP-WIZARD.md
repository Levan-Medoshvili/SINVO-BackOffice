# First-install configuration wizard (preview)

This is a **non-installing preview** of the future SINVO setup UI. It validates
form fields but **does not** authenticate database users, download packages,
write credentials, or deploy BackOffice. It must not be treated as a completed
installer.

On the clean Rocky Linux 9 VM with the BackOffice Staging checkout:

```bash
python3 deploy/rocky/setup_wizard.py
```

The wizard listens ONLY on `127.0.0.1:8765`. On a Windows workstation run:
```powershell
ssh -L 8765:127.0.0.1:8765 root@YOUR_NEW_VM_IP
```
Open the URL (including its random token) printed by the wizard in a browser
on the Windows machine. Do not expose this port on the public LAN.

The wizard collects company name, identification number, address, mobile,
company email, admin username/password, database engine, local/remote choice,
remote host/port, and remote login. Remote PostgreSQL/MySQL/MSSQL will require
an actual authenticated connect-and-query check before real installation.
Local database automation currently supports PostgreSQL only.

Future work: a separately issued installation grant for the Update Server,
a publisher-pinned trusted Ed25519 key bundled in the installer, secure
artifact extraction, authenticated database verification, temporary secret
handling, and a privileged deployment worker that retains job state.
