import hashlib
import hmac
from datetime import timedelta
from uuid import UUID
from django.conf import settings
from django.contrib.auth import authenticate
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from .access import employee_access, branch_allowed, operator_data, decode_authorization, count_login_attempt
from .authentication import RegisterAuthentication, IsRegister
from rest_framework.exceptions import AuthenticationFailed
from .models import Location, Register, DeviceEnrollment, CashierSession


@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([])
def sign_in(request):
    body = request.data
    if not isinstance(body, dict): return Response({"detail": "Invalid sign-in request."}, status=400)
    username, password = body.get("username"), body.get("password")
    if not isinstance(username, str) or not 1 <= len(username) <= 150 or not isinstance(password, str) or not 1 <= len(password) <= 1024:
        return Response({"detail": "Enter a username and password."}, status=400)
    username = username.strip()
    address = request.META.get("REMOTE_ADDR", "unknown")
    if address in {"127.0.0.1", "::1"}: address = request.META.get("HTTP_X_REAL_IP", address)
    if not count_login_attempt("ip:" + address, 100) or not count_login_attempt("user:" + username.casefold(), 10):
        return Response({"detail": "Too many attempts. Try again in five minutes."}, status=429)
    user = authenticate(request, username=username.strip(), password=password)
    access = employee_access(user) if user else None
    if not access or access.application not in {"cashier", "both"}:
        return Response({"detail": "Sign-in failed or Cashier access is not permitted."}, status=403)
    branch_name = body.get("branch_name", "")
    if not isinstance(branch_name, str) or not branch_name.strip() or len(branch_name) > 150:
        return Response({"detail": "Configure the branch name first."}, status=400)
    try:
        installation_id = UUID(str(body.get("installation_id")))
        secret = body["installation_secret"]
        hint = body.get("branch_address", "")
        if not isinstance(secret, str) or not 40 <= len(secret) <= 100 or not isinstance(hint, str) or len(hint) > 300: raise ValueError()
    except (ValueError, KeyError, TypeError):
        return Response({"detail": "Invalid installation identity."}, status=400)
    digest = hashlib.sha256(secret.encode()).hexdigest()
    approved = DeviceEnrollment.objects.select_related("register").filter(pk=installation_id).first()
    if approved:
        if not hmac.compare_digest(approved.secret_hash, digest): return Response({"detail": "Device identity does not match."}, status=403)
        branches = Location.objects.filter(pk=approved.register.location_id, company=access.company, kind="branch", active=True)
    else:
        branches = Location.objects.filter(company=access.company, kind="branch", active=True).filter(Q(name__iexact=branch_name.strip()) | Q(code=branch_name.strip()))
    if branches.count() != 1 or not branch_allowed(access, branches.first()):
        return Response({"detail": "This branch is unavailable or not assigned to your account."}, status=403)
    branch = branches.get()
    with transaction.atomic():
        # Scope enrollment serialization to this branch; no client-selected company is trusted.
        Location.objects.select_for_update().get(pk=branch.pk)
        enrollment = DeviceEnrollment.objects.select_related("register").filter(pk=installation_id).first()
        if enrollment:
            register = enrollment.register
            if not hmac.compare_digest(enrollment.secret_hash, digest) or register.location_id != branch.pk or not register.active:
                return Response({"detail": "This installation does not match the enrolled register."}, status=403)
        else:
            legacy = None
            if request.META.get("HTTP_AUTHORIZATION"):
                try: legacy = RegisterAuthentication().authenticate(request)
                except AuthenticationFailed:
                    return Response({"detail": "Existing register credential is invalid. Contact the administrator before migrating this device."}, status=403)
            if legacy:
                register = legacy[1]
                if register.location_id != branch.pk or DeviceEnrollment.objects.filter(register=register).exists():
                    return Response({"detail": "Existing register does not match this installation."}, status=403)
            else:
                return Response({"detail": "This POS needs BackOffice approval or a one-use pairing code before signing in.", "enrollment_required": True}, status=403)
            DeviceEnrollment.objects.create(installation_id=installation_id, register=register, secret_hash=digest, address_hint=hint, enrolled_by=user)
        credential = register.issue_token()
        session = CashierSession.objects.create(register=register, user=user, expires_at=timezone.now() + timedelta(days=settings.SIMPLEPOS_OFFLINE_LOGIN_DAYS))
        data = operator_data(session)
    return Response({"operator": data, "register_credential": credential,
        "branch": {"id": str(branch.pk), "name": branch.name, "address": branch.address},
        "register": {"id": str(register.pk), "name": register.name}})


@api_view(["POST"])
@permission_classes([IsRegister])
def sign_out(request):
    if not isinstance(request.data, dict): return Response({"detail": "Invalid request."}, status=400)
    try:
        session = decode_authorization(request.data.get("authorization"), request.auth)
        CashierSession.objects.filter(pk=session.pk, ended_at__isnull=True).update(ended_at=timezone.now())
    except PermissionDenied: pass
    return Response({"status": "signed_out"})
