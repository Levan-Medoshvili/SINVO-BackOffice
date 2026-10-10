"""Read-only update discovery in the BackOffice admin UI.

An installer MUST run independently of Gunicorn under a narrowly scoped service
account; this module intentionally cannot execute commands or replace application files.
"""
import json
import os
from pathlib import Path

from django.conf import settings
from sinvo_release_version import installed_release
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .access import backoffice


def _identity():
    path = Path(os.environ.get("SINVO_CLIENT_IDENTITY_FILE", "/var/lib/sinvo-backoffice/update-client/identity.json"))
    # Do not create an identity from an HTTP request. Provisioning is handled by the client timer.
    if not path.is_file() or path.is_symlink():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(state, dict) or
            not isinstance(state.get("credential"), str) or
            len(state["credential"]) < 48):
            return None
        return state
    except (ValueError, OSError, PermissionError):
        return None


@never_cache
@backoffice("manage_updates")
def page(request):
    if not request.user.is_superuser:
        raise PermissionDenied
    return render(request, "backoffice/system_updates.html", {
        "nav": "system-updates",
        "installed_version": installed_release()["label"],
        "installed_revision": installed_release()["revision"],
        "enrollment_configured": _identity() is not None,
    })


@never_cache
@require_POST
@backoffice("manage_updates")
def check(request):
    if not request.user.is_superuser:
        raise PermissionDenied
    state = _identity()
    if state is None:
        return JsonResponse({"status": "unconfigured",
                             "message": "Automatic enrollment is not configured on this server yet."})
    # HTTP calls are read-only and have a timeout. Client token is never returned to the browser.
    from sinvo_enrollment import _request
    endpoint = os.environ.get("SINVO_UPDATE_ENDPOINT", "https://dev-updates.sinvo.ge")
    try:
        code, auth = _request(endpoint, "/api/v1/client/enrollment-status/",
                              token=state["credential"])
        if code != 200:
            return JsonResponse({"status": "unavailable", "message": "Unable to verify installation authorization."}, status=503)
        entitlement = auth.get("status")
        if entitlement != "approved":
            return JsonResponse({"status": entitlement, "message": {
                "pending_approval": "This installation is awaiting provider approval.",
                "updates_suspended": "Update access is suspended.",
                "subscription_expired": "The update subscription has expired.",
            }.get(entitlement, "Updates are unavailable.")})
        code, release = _request(endpoint, "/api/v1/client/releases/latest/?product=backoffice",
                                  token=state["credential"])
        if code != 200:
            return JsonResponse({"status": "unavailable", "message": "Unable to check approved releases."}, status=503)
        item = release.get("release") if release.get("update_available") else None
        if not item:
            return JsonResponse({"status": "current", "message": "No newer approved BackOffice release is available."})
        return JsonResponse({"status": "available", "release": {
            "version": item.get("version", ""),
            "notes": item.get("notes", ""),
            "size": item.get("size", 0),
            "sha256": item.get("sha256", ""),
        }})
    except (OSError, RuntimeError, ValueError) as exc:
        return JsonResponse({"status": "unavailable", "message": "Update Server cannot be reached securely."}, status=503)
