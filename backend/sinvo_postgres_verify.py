"""SINVO isolated PostgreSQL backup/restore verification (root-only CLI).

Creates a private root-owned backup, verifies checksum and archive listing,
restores into a newly generated disposable database, compares table counts,
and drops ONLY that uniquely created disposable database. It does not stop
BackOffice, migrate its database, or activate a release.

A successful test is NOT proof that future schema migrations are reversible.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys

SAFE_DB = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
PREFIX = "sinvo_verify_"
TABLES_SQL = "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE';"


def isolated_name():
    return PREFIX + secrets.token_hex(8)


def checked_name(name):
    if not SAFE_DB.fullmatch(name):
        raise ValueError("Unsafe PostgreSQL database identifier")
    return name


def ensure_backup_dir(path):
    directory = Path(path)
    if directory.is_symlink() or not directory.is_dir():
        raise RuntimeError("Backup directory missing or symlinked")
    stat = directory.stat()
    if stat.st_uid != 0 or stat.st_mode & 0o077:
        raise RuntimeError("Backup directory must be root-owned and mode 0700")
    return directory


def execute(args, *, input_file=None, output_file=None):
    result = subprocess.run(args, stdin=input_file, stdout=output_file or subprocess.PIPE,
                            stderr=subprocess.PIPE, check=False)
    if result.returncode:
        raise RuntimeError(f"Database tool {args[0]} failed with exit code {result.returncode}")
    return result.stdout


def table_count(database):
    output = execute(["runuser", "-u", "postgres", "--", "psql",
                      "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1",
                      "-d", checked_name(database), "-c", TABLES_SQL])
    return int(output.decode("ascii").strip())


def verify_backup(database, backup_dir, *, runner=execute):
    if os.geteuid() != 0:
        raise PermissionError("Root is required; database tool runs as postgres")
    database = checked_name(database)
    if database.startswith(PREFIX):
        raise ValueError("Source database must not use reserved verification prefix")
    directory = ensure_backup_dir(backup_dir)
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    file_path = directory / f"sinvo-preupdate-{now}-{secrets.token_hex(4)}.dump"
    temp_db = isolated_name()
    created = False
    backup_completed = False
    # Prevent simultaneous validation jobs on the host.
    lock_fd = os.open("/run/lock/sinvo-postgres-verify.lock", os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        source_count = table_count(database)
        if source_count <= 0:
            raise RuntimeError("Source database has no public tables")
        fd = os.open(file_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "wb") as output:
            runner(["runuser", "-u", "postgres", "--", "pg_dump",
                    "--format=custom", "--no-owner", "--no-acl",
                    "--dbname=" + database], output_file=output)
            output.flush()
            os.fsync(output.fileno())
        if file_path.stat().st_size <= 0:
            raise RuntimeError("Empty PostgreSQL backup")
        digest = hashlib.file_digest(file_path.open("rb"), "sha256").hexdigest()
        runner(["pg_restore", "--list", str(file_path)])
        checksum_path = Path(str(file_path) + ".sha256")
        with open(checksum_path, "x", encoding="ascii") as handle:
            os.chmod(checksum_path, 0o600)
            handle.write(f"{digest}  {file_path.name}\n")
        runner(["runuser", "-u", "postgres", "--", "createdb", temp_db])
        created = True
        with file_path.open("rb") as source:
            runner(["runuser", "-u", "postgres", "--", "pg_restore",
                    "--exit-on-error", "--no-owner", "--no-acl",
                    "--dbname=" + temp_db], input_file=source)
        restored_count = table_count(temp_db)
        if restored_count != source_count:
            raise RuntimeError("Restored table count differs from source")
        backup_completed = True
        return {"status": "verified", "backup": str(file_path),
                "checksum": str(checksum_path), "sha256": digest,
                "source_tables": source_count, "restored_tables": restored_count,
                "temporary_database": temp_db, "temporary_database_removed": True}
    finally:
        if created:
            # Never drop the live database or a preexisting manually-created test DB.
            try:
                runner(["runuser", "-u", "postgres", "--", "dropdb", "--if-exists", temp_db])
            except Exception as cleanup_error:
                raise RuntimeError(f"Restore verification database cleanup failed: {temp_db}") from cleanup_error
        if not backup_completed:
            # Keep a completed dump for incident diagnosis; discard empty/partial dumps.
            if file_path.exists() and file_path.stat().st_size == 0:
                file_path.unlink()
        os.close(lock_fd)


def main():
    parser = argparse.ArgumentParser(description="Back up and test restore using an isolated PostgreSQL database")
    parser.add_argument("--database", default="simplepos_erp")
    parser.add_argument("--directory", default="/var/backups/pos-erp")
    args = parser.parse_args()
    try:
        result = verify_backup(args.database, args.directory)
        print(json.dumps(result, indent=2))
    except (OSError, ValueError, RuntimeError, PermissionError) as exc:
        print(f"Backup verification failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
