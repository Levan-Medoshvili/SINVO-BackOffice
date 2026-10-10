"""SINVO BackOffice enrollment and safe update discovery.

Stand-alone Python 3.11 client: run via an installation-specific systemd timer.
No Django database, sales data, or remote installer is touched.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
import urllib.error
import urllib.request
import uuid

DEFAULT_ENDPOINT = "https://dev-updates.sinvo.ge"
DEFAULT_STATE = "/var/lib/sinvo-backoffice/update-client/identity.json"


def _identity_file(path):
    state_path = Path(path)
    if state_path.exists():
        if state_path.is_symlink():
            raise RuntimeError("Identity must not be a symlink")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if set(state) != {"installation_id", "credential"}:
            raise RuntimeError("Invalid stored SINVO identity")
        uuid.UUID(state["installation_id"])
        if not isinstance(state["credential"], str) or len(state["credential"]) < 48:
            raise RuntimeError("Invalid stored SINVO credential")
        return state
    # Store the token once in the persistent data path. Rebuilds must not overwrite it.
    state_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if state_path.parent.is_symlink():
        raise RuntimeError("Identity directory must not be a symlink")
    state = {"installation_id": str(uuid.uuid4()), "credential": secrets.token_urlsafe(48)}
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(str(state_path), flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        state_path.unlink(missing_ok=True)
        raise
    return state


def _request(endpoint, path, token=None, payload=None):
    endpoint = endpoint.rstrip("/")
    if not endpoint.startswith("https://") or "@" in endpoint or "/" in endpoint[8:]:
        raise ValueError("SINVO endpoint must be HTTPS origin only")
    headers = {"Accept": "application/json", "User-Agent": "SINVO-BackOffice-Enrollment/1"}
    if token:
        headers["Authorization"] = "Bearer " + token
    body = None
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(endpoint + path, data=body, headers=headers,
                                     method="POST" if payload is not None else "GET")
    # Do not follow redirects: never risk forwarding installation credentials.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(request, timeout=12) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 409 and path.endswith("/enroll/"):
            return 409, {"status": "already_registered"}
        if error.code in (401, 403, 404):
            return error.code, {"error": "client_not_authorized"}
        raise RuntimeError(f"SINVO request failed: HTTP {error.code}") from None


def company_name_from_backoffice():
    """Read the existing configured company; no extra customer configuration."""
    import django
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()
    from commerce.models import Company
    return (Company.objects.filter(installation_slot=1)
            .values_list("name", flat=True).first() or "").strip()


def run(endpoint, state_path, name, version, company_name=""):
    state = _identity_file(state_path)
    token = state["credential"]
    status_code, current = _request(endpoint, "/api/v1/client/enrollment-status/", token=token)
    if status_code == 401:
        status_code, current = _request(endpoint, "/api/v1/client/enroll/", payload={
            "installation_id": state["installation_id"],
            "name": name,
            "kind": "backoffice",
            "credential_sha256": hashlib.sha256(token.encode("utf-8")).hexdigest(),
        })
        if status_code == 409:
            # Credentials rejected for an existing UUID: do not overwrite identity
            # or bypass review. Administrative recovery is required.
            raise RuntimeError("Enrollment collision or revoked credentials; contact SINVO support")
    if status_code == 202:
        print("SINVO enrollment submitted: pending approval")
        return
    if status_code != 200:
        print("SINVO enrollment status unavailable")
        return
    status = current.get("status")
    if status == "pending_approval":
        print("SINVO enrollment pending approval")
        return
    if status not in ("approved", "updates_suspended", "subscription_expired"):
        raise RuntimeError("Unexpected SINVO enrollment status")
    hb_code, _ = _request(endpoint, "/api/v1/client/heartbeat/", token=token,
                          payload={"software_version": version, **({"company_name": company_name} if company_name else {})})
    if hb_code != 200:
        raise RuntimeError(f"Heartbeat rejected: HTTP {hb_code}")
    if status != "approved":
        print(f"SINVO connected, update access: {status}")
        return
    code, release = _request(endpoint, "/api/v1/client/releases/latest/?product=backoffice", token=token)
    if code != 200:
        raise RuntimeError(f"Update discovery failed: HTTP {code}")
    if release.get("update_available"):
        info = release.get("release") or {}
        print(f"SINVO update available: {info.get('version', 'unknown')}; install remains manual")
    else:
        print("SINVO connected; no new approved release")


def main():
    parser = argparse.ArgumentParser(description="Enroll BackOffice and check for approved updates")
    parser.add_argument("--endpoint", default=os.getenv("SINVO_UPDATE_ENDPOINT", DEFAULT_ENDPOINT))
    parser.add_argument("--state", default=os.getenv("SINVO_CLIENT_IDENTITY_FILE", DEFAULT_STATE))
    parser.add_argument("--name", default=os.getenv("SINVO_INSTALLATION_NAME", "SINVO BackOffice"))
    parser.add_argument("--version", default=None, help="Override detected version for testing only")
    args = parser.parse_args()
    try:
        configured_company = company_name_from_backoffice()
        display_name = ("SINVO BackOffice — " + configured_company) if configured_company else args.name
        from sinvo_release_version import installed_release
        detected = installed_release()
        if not detected["version_known"] and args.version is None:
            print("SINVO: legacy/unversioned installation; update comparison is provisional")
        run(args.endpoint, args.state, display_name,
            args.version if args.version is not None else detected["version"],
            company_name=configured_company)
    except (OSError, RuntimeError, ValueError, urllib.error.URLError) as err:
        print("SINVO update enrollment check failed:", str(err), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
