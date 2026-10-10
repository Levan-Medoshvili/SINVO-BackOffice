"""Read-only SINVO update preflight: never install, migrate or restart.

The installer must run in an independent privileged service and must NOT use
this preflight as an authorization bypass. These checks explain blocked states.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import stat
import sys

MIN_FREE_BYTES = 1024 * 1024 * 1024


def inspect_installation(root="/opt/pos-erp", envfile="/etc/pos-erp/backend.env",
                         download_directory="/var/lib/sinvo-backoffice/downloads",
                         min_free_bytes=MIN_FREE_BYTES):
    findings = []
    def record(code, ok, reason):
        findings.append({"code": code, "ok": bool(ok), "message": reason})
    root = Path(root)
    active = root / "current"
    try:
        target = active.resolve(strict=True)
        valid = active.is_symlink() and target.is_dir() and target.parent == (root / "releases").resolve(strict=True)
        record("release_layout", valid, "Current release points to a managed release directory" if valid else "Current release layout is not recognized")
    except (OSError, RuntimeError):
        record("release_layout", False, "Current release link cannot be resolved")
    try:
        record("config", Path(envfile).is_file(),
               "BackOffice configuration exists" if Path(envfile).is_file() else "BackOffice configuration is missing")
    except OSError:
        record("config", False, "Cannot inspect BackOffice configuration")
    try:
        directory = Path(download_directory)
        valid = directory.is_dir() and not directory.is_symlink() and not (directory.stat().st_mode & (stat.S_IWGRP | stat.S_IWOTH))
        record("download_directory", valid, "Private download directory exists" if valid else "Download directory must be private and not a symlink")
        available = shutil.disk_usage(directory).free if valid else 0
        record("disk_space", available >= min_free_bytes,
               "At least 1 GiB free space available" if available >= min_free_bytes else "Insufficient free space in download filesystem")
    except OSError:
        record("download_directory", False, "Download directory cannot be inspected")
        record("disk_space", False, "Free space cannot be determined")
    # A checksum alone does not authenticate a release. No signing configuration
    # is deployed yet, so applying any archive MUST remain blocked.
    record("publisher_signature", False, "Mandatory publisher signature verification is not yet configured")
    record("database_recovery", False, "Database backup and schema-aware recovery have not been verified")
    return {"ready_to_install": all(item["ok"] for item in findings),
            "checks": findings}


def main():
    parser = argparse.ArgumentParser(description="Read-only SINVO installation preflight")
    parser.add_argument("--root", default="/opt/pos-erp")
    parser.add_argument("--envfile", default="/etc/pos-erp/backend.env")
    parser.add_argument("--downloads", default="/var/lib/sinvo-backoffice/downloads")
    args = parser.parse_args()
    print(json.dumps(inspect_installation(args.root,args.envfile,args.downloads),indent=2))
    return 0

if __name__=="__main__":
    sys.exit(main())
