"""Standalone staging preparation worker. Never executes or installs a package.

Status files are written atomically under a private service-user directory.
The browser can read only the public progress fields via Django; secrets, full
paths and artifact contents are deliberately excluded.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from datetime import datetime, timezone

from sinvo_download import download_verified
from sinvo_enrollment import DEFAULT_ENDPOINT, DEFAULT_STATE

DEFAULT_PROGRESS = "/var/lib/sinvo-backoffice/update-client/progress.json"


def save_progress(filename, stage, percent, message, version=""):
    path = Path(filename)
    if not path.parent.is_dir() or path.parent.is_symlink():
        raise RuntimeError("Private progress directory must already exist")
    if path.is_symlink():
        raise RuntimeError("Progress file cannot be a symlink")
    data = {
        "stage": stage, "percent": max(0, min(100, int(percent))),
        "message": message[:180], "version": version[:64],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    fd, tempname = tempfile.mkstemp(prefix=".progress-", dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tempname, path)
    finally:
        if os.path.exists(tempname):
            os.unlink(tempname)


def prepare(endpoint, identity, downloads, progress):
    def report(stage, percent, message):
        save_progress(progress, stage, percent, message)
    report("checking", 3, "Checking installation entitlement")
    try:
        result = download_verified(endpoint, identity, downloads, progress=report)
        save_progress(progress, "ready", 100,
                      "Package verified and quarantined; installation is disabled",
                      result["version"])
        return result
    except Exception:
        # Do not expose network errors, credentials, or filesystem paths in UI.
        save_progress(progress, "failed", 0,
                      "Preparation failed. Check the updater service logs.")
        raise


def main():
    parser = argparse.ArgumentParser(description="Prepare and verify package only")
    parser.add_argument("--endpoint", default=os.getenv("SINVO_UPDATE_ENDPOINT", DEFAULT_ENDPOINT))
    parser.add_argument("--state", default=os.getenv("SINVO_CLIENT_IDENTITY_FILE", DEFAULT_STATE))
    parser.add_argument("--downloads", required=True)
    parser.add_argument("--progress", default=os.getenv("SINVO_UPDATE_PROGRESS_FILE", DEFAULT_PROGRESS))
    args = parser.parse_args()
    try:
        result = prepare(args.endpoint, args.state, args.downloads, args.progress)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Update preparation failed: {exc}", file=sys.stderr)
        return 1
    print(f"Ready for future installation: {result['version']} (verified SHA-256)")
    return 0

if __name__ == "__main__":
    sys.exit(main())
