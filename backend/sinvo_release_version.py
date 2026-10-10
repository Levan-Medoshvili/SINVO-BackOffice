"""Build metadata shared by the updater and the BackOffice UI.

Legacy installs predate this metadata and should NOT claim a known semantic
version. Their Git revision is useful diagnostic information, not a semver.
"""
import json
import os
from pathlib import Path

from django.conf import settings


def installed_release():
    override = os.environ.get("SINVO_SOFTWARE_VERSION", "").strip()
    marker = Path(settings.BASE_DIR) / ".sinvo-build.json"
    version = ""
    revision = os.environ.get("SIMPLEPOS_BUILD_REVISION", "").strip()
    if marker.is_file():
        try:
            payload = json.loads(marker.read_text(encoding="utf-8"))
            version = str(payload.get("version", "")).strip()
            revision = str(payload.get("revision", "")).strip() or revision
        except (OSError, ValueError, TypeError):
            pass
    if override:
        version = override
    if not version or version == "0.1.0" and not marker.is_file() and not override:
        return {"version": "", "label": "Legacy / unversioned",
                "revision": revision, "version_known": False}
    return {"version": version, "label": version,
            "revision": revision, "version_known": True}
