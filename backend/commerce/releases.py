"""Read-only delivery of release-operator-published files; private keys never belong here."""
import json
import re
from django.conf import settings
from django.http import FileResponse, Http404
from django.views.decorators.http import require_GET


@require_GET
def release_file(request, platform, filename):
    if platform not in {"win-x64", "linux-x64"} or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,150}", filename): raise Http404()
    root = (settings.SIMPLEPOS_RELEASE_DIR / platform).resolve()
    target = (root / filename).resolve()
    if target.parent != root or not target.is_file(): raise Http404()
    if filename not in {"manifest.json", "manifest.sig"}:
        try:
            manifest = json.loads((root / "manifest.json").read_text())
            if filename != manifest["filename"] or not filename.endswith(".zip" if platform == "win-x64" else ".AppImage"): raise Http404()
        except (OSError, ValueError, KeyError): raise Http404() from None
    response = FileResponse(target.open("rb"), content_type="application/json" if filename == "manifest.json" else "application/octet-stream")
    response["Cache-Control"] = "no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response
