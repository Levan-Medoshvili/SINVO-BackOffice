#!/usr/bin/env python3
"""Local-only first-install configuration wizard.

No installation, filesystem changes or remote downloads. The installer must
independently validate signed artifacts, database credentials and privileges
before consuming wizard configuration in a later phase.
"""
import getpass
import html
import ipaddress
import json
import os
import re
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

FIELDS = ("company_name", "identification_number", "company_address", "mobile",
          "company_email", "admin_username", "admin_password", "database_engine",
          "database_location", "database_host", "database_port", "database_name",
          "database_username", "database_password")
ALLOWED_DATABASES = {"postgres", "mysql", "mssql"}
HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SINVO BackOffice setup</title><style>
:root{font-family:system-ui,sans-serif;color-scheme:dark}
body{margin:0;background:#101d22;color:#e6f3f3;display:grid;place-items:center;min-height:100vh}
main{width:min(900px,92vw);background:#1a2c32;border:1px solid #385057;border-radius:20px;padding:28px}
h1{margin-top:0}fieldset{border:1px solid #385057;border-radius:12px;margin:18px 0;padding:18px}
legend{color:#91d9c8;font-weight:bold}label{display:grid;gap:6px;margin:12px 0}
input,select{padding:12px;border:1px solid #496269;border-radius:8px;background:#101d22;color:#fff;max-width:100%}
button{background:#2c806a;border:0;color:white;border-radius:9px;padding:14px 22px;font-weight:bold;cursor:pointer}
small{color:#bad0d4}.error{color:#ffaca7} .grid{display:grid;grid-template-columns:1fr 1fr;gap:0 18px}
@media(max-width:640px){.grid{grid-template-columns:1fr}}
</style></head><body><main><h1>SINVO BackOffice installer</h1>
<p>Initial configuration · No software will be installed at this step.</p>
{message}
<form method="post" action="/submit?token={token}" autocomplete="off">
<fieldset><legend>Company information</legend><div class="grid">
<label>Company name * <input name="company_name" maxlength="150" required></label>
<label>Identification number * <input name="identification_number" maxlength="32" required></label>
<label>Company address <input name="company_address" maxlength="300"></label>
<label>Mobile <input name="mobile" maxlength="40"></label>
<label>Email <input name="company_email" type="email" maxlength="254"></label>
</div></fieldset>
<fieldset><legend>First administrator</legend><div class="grid">
<label>Username * <input name="admin_username" maxlength="150" required></label>
<label>Password * <input name="admin_password" type="password" minlength="12" required></label>
</div><small>The password is not shown in logs and will not be saved by this preview wizard.</small></fieldset>
<fieldset><legend>Database</legend><div class="grid">
<label>Engine <select name="database_engine"><option value="postgres">PostgreSQL</option>
<option value="mysql">MySQL</option><option value="mssql">Microsoft SQL Server</option></select></label>
<label>Location <select name="database_location"><option value="local">Install locally</option>
<option value="remote">Existing database server</option></select></label>
<label>Server IP/host (remote) <input name="database_host" maxlength="200" placeholder="10.0.110.50"></label>
<label>Port (remote) <input name="database_port" inputmode="numeric" maxlength="5" placeholder="5432"></label>
<label>Database name <input name="database_name" maxlength="63" value="simplepos_erp"></label>
<label>Database username (remote) <input name="database_username" maxlength="100"></label>
<label>Database password (remote) <input name="database_password" type="password"></label>
</div></fieldset>
<button type="submit">Validate configuration</button></form>
<p><small>Accessible only through localhost. For remote administration, use an SSH tunnel.</small></p>
</main></body></html>"""


def validate(values):
    errors = []
    for name, maximum in (("company_name", 150), ("identification_number", 32),
                          ("company_address", 300), ("mobile", 40), ("company_email", 254),
                          ("admin_username", 150), ("database_host", 200),
                          ("database_username", 100), ("database_name", 63)):
        value = values.get(name, "")
        if len(value) > maximum or any(ord(c) < 32 for c in value):
            errors.append("Invalid value: " + name)
    for name in ("company_name", "identification_number", "admin_username"):
        if not values.get(name, "").strip():
            errors.append("Required: " + name)
    if len(values.get("admin_password", "")) < 12:
        errors.append("Administrator password must be at least 12 characters")
    if values.get("company_email") and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", values["company_email"]):
        errors.append("Invalid company email")
    if values.get("database_engine") not in ALLOWED_DATABASES:
        errors.append("Unsupported database engine")
    if values.get("database_location") not in {"local", "remote"}:
        errors.append("Invalid database location")
    if values.get("database_location") == "local" and values.get("database_engine") != "postgres":
        errors.append("Local database automation currently supports PostgreSQL only")
    if values.get("database_location") == "remote":
        if not values.get("database_host") or not values.get("database_username") or not values.get("database_password"):
            errors.append("Remote database host, username and password are required")
        try:
            port = int(values.get("database_port", ""))
            if not 1 <= port <= 65535: raise ValueError()
        except ValueError:
            errors.append("Valid remote database port required")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,62}", values.get("database_name", "")):
        errors.append("Use a simple database identifier (letters, digits, underscore)")
    return errors


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Never log URL query tokens or submitted values.
        pass

    def respond(self, code, body):
        content = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def authorized(self):
        return secrets.compare_digest(
            parse_qs(urlsplit(self.path).query).get("token", [""])[0], self.server.setup_token)

    def do_GET(self):
        if urlsplit(self.path).path != "/" or not self.authorized():
            return self.respond(404, "<h1>Not found</h1>")
        return self.respond(200, HTML.replace("{token}", self.server.setup_token).replace("{message}", ""))

    def do_POST(self):
        if urlsplit(self.path).path != "/submit" or not self.authorized():
            return self.respond(404, "<h1>Not found</h1>")
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            size = 0
        if not 0 < size <= 8192:
            return self.respond(413, "<h1>Invalid form size</h1>")
        body = parse_qs(self.rfile.read(size).decode("utf-8"), keep_blank_values=True)
        values = {key: body.get(key, [""])[0] for key in FIELDS}
        errors = validate(values)
        if errors:
            return self.respond(400, HTML.replace("{token}", self.server.setup_token).replace("{message}", '<p class="error">' + html.escape("; ".join(errors)) + "</p>"))
        # Deliberately do not persist the password; currently a safe UI prototype.
        safe = {k: v for k,v in values.items()
                if k not in {"admin_password", "database_password"}}
        print("Validated wizard input (without passwords): " + json.dumps(safe, ensure_ascii=False), flush=True)
        return self.respond(200, """<main><h1>Configuration validated</h1>
<p>Configuration has passed field validation. No packages, databases or application
files have been installed. Remote authentication checks and signed deployment
must be completed before enabling installation.</p></main>""")


def main():
    token = secrets.token_urlsafe(32)
    server = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
    server.setup_token = token
    print("SINVO configuration wizard: http://127.0.0.1:8765/?token=" + token, flush=True)
    print("Run from a local browser, or SSH tunnel: ssh -L 8765:127.0.0.1:8765 root@VM_IP", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
