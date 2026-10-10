"""Download and SHA-256 verify an approved SINVO release without installing it.

Run as the dedicated service user. Output is a *quarantined* data file: never
extract, execute, or automatically activate it. Requires an approved client
identity and HTTPS verification.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import urllib.request
from urllib.parse import urlsplit

from sinvo_enrollment import _request, _identity_file, DEFAULT_ENDPOINT, DEFAULT_STATE

SHA256 = re.compile(r"^[0-9a-f]{64}$")
MAX_SIZE = 512 * 1024 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def download_verified(endpoint, state_path, output_directory):
    endpoint = endpoint.rstrip("/")
    u = urlsplit(endpoint)
    if u.scheme != "https" or not u.hostname or u.username or u.password or u.path or u.query or u.fragment:
        raise ValueError("HTTPS endpoint must be a bare origin")
    state = _identity_file(state_path)
    token = state["credential"]
    status, auth = _request(endpoint, "/api/v1/client/enrollment-status/", token=token)
    if status != 200 or auth.get("status") != "approved":
        raise RuntimeError("Installation lacks active update entitlement")
    status, latest = _request(endpoint, "/api/v1/client/releases/latest/?product=backoffice", token=token)
    if status != 200 or not latest.get("update_available"):
        raise RuntimeError("No newer approved BackOffice release")
    release = latest.get("release") or {}
    release_id, size, sha = release.get("id"), release.get("size"), release.get("sha256")
    expected_path = f"/api/v1/client/releases/{release_id}/download/"
    if (type(release_id) is not int or release_id < 1 or
        type(size) is not int or not 0 < size <= MAX_SIZE or
        not isinstance(sha, str) or not SHA256.fullmatch(sha) or
        release.get("download_path") != expected_path or
        release.get("product") != "backoffice" or
        release.get("channel") != "staging"):
        raise RuntimeError("Invalid or untrusted release metadata")
    destination = Path(output_directory)
    if not destination.is_dir() or destination.is_symlink() or destination.stat().st_mode & 0o022:
        raise RuntimeError("Create a private, non-world-writable download directory first")
    filename = f"sinvo-backoffice-release-{release_id}-{sha[:12]}.tar.gz"
    target = destination / filename
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(target, flags, 0o600)
    digest = hashlib.sha256()
    bytes_read = 0
    try:
        request = urllib.request.Request(
            endpoint + expected_path,
            headers={"Authorization": "Bearer " + token,
                     "User-Agent": "SINVO-BackOffice-Verifier/1"},
            method="GET")
        with os.fdopen(fd, "wb") as output, urllib.request.build_opener(NoRedirect).open(request, timeout=120) as response:
            if response.status != 200:
                raise RuntimeError("Unexpected HTTP download status")
            while True:
                chunk = response.read(128 * 1024)
                if not chunk:
                    break
                bytes_read += len(chunk)
                if bytes_read > size:
                    raise RuntimeError("Artifact exceeds declared size")
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if bytes_read != size or digest.hexdigest() != sha:
            raise RuntimeError("Artifact failed length or SHA-256 verification")
        return {"file": str(target), "bytes": bytes_read, "sha256": sha,
                "version": release.get("version", "")}
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(description="Verify SINVO update download only; never install")
    parser.add_argument("--endpoint", default=os.getenv("SINVO_UPDATE_ENDPOINT", DEFAULT_ENDPOINT))
    parser.add_argument("--state", default=os.getenv("SINVO_CLIENT_IDENTITY_FILE", DEFAULT_STATE))
    parser.add_argument("--directory", required=True, help="Private existing directory for verified archives")
    args = parser.parse_args()
    try:
        result = download_verified(args.endpoint, args.state, args.directory)
        print("Verified package:", result["file"])
        print("Release:", result["version"], "size:", result["bytes"], "sha256:", result["sha256"])
        return 0
    except (OSError, ValueError, RuntimeError) as error:
        print("Package download/verification failed:", str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
