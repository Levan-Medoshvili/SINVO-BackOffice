#!/usr/bin/env python3
"""Upload an immutable Staging build; never install or activate it."""
import hashlib
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.request
import uuid

if len(sys.argv) != 4:
    raise SystemExit("Usage: sinvo-publish.py PRODUCT FILE HTTPS_ENDPOINT")
product, filename, endpoint = sys.argv[1:]
if product not in {"backoffice", "cashier", "agent"} or endpoint != "https://dev-updates.sinvo.ge/api/v1/releases/publish/":
    raise SystemExit("Invalid product or endpoint")
token = os.environ.get("SINVO_PUBLISH_TOKEN", "")
if len(token) < 32:
    raise SystemExit("Missing Jenkins publisher token")
path = pathlib.Path(filename)
if not path.is_file():
    raise SystemExit("Build artifact missing")
data = path.read_bytes()
if not data:
    raise SystemExit("Empty build artifact")
version = os.environ.get("SINVO_RELEASE_VERSION", "").strip()
if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?", version):
    raise SystemExit("Specify valid SINVO_RELEASE_VERSION, e.g. 0.5.0+staging.123")
manifest = {
    "product": product, "channel": "staging", "version": version,
    "sha256": hashlib.sha256(data).hexdigest(), "size": len(data),
    "notes": os.environ.get("SINVO_RELEASE_NOTES", "Automated Jenkins Staging build")[:10000],
}
canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
boundary = "sinvo" + uuid.uuid4().hex
parts = []
for key, value in [("manifest", canonical)]:
    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n".encode())
parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="artifact"; filename="package.bin"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode() + data + b"\r\n")
parts.append(f"--{boundary}--\r\n".encode())
request = urllib.request.Request(endpoint, data=b"".join(parts), headers={
    "Authorization": "Bearer " + token,
    "Content-Type": f"multipart/form-data; boundary={boundary}",
    "User-Agent": "SINVO-Jenkins-Publisher/1.0",
}, method="POST")
try:
    with urllib.request.urlopen(request, timeout=90) as response:
        output = json.loads(response.read())
        print(f"Release accepted as {output.get('status')} (ID {output.get('id')})")
except urllib.error.HTTPError as exc:
    print(f"Publication failed: HTTP {exc.code}; {exc.read(1500).decode(errors='replace')}", file=sys.stderr)
    raise SystemExit(1)
