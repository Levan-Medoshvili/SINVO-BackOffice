"""Approval and short-lived pairing authorize devices, never employee logins."""
import hashlib
import hmac
import secrets
from datetime import timedelta
from uuid import UUID
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from .access import count_login_attempt
from .models import Company, Installation, Location, Register, EnrollmentRequest, PairingCode, DeviceEnrollment

ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"

def client_address(request):
    address = request.META.get("REMOTE_ADDR", "unknown")
    return request.META.get("HTTP_X_REAL_IP", address) if address in {"127.0.0.1", "::1"} else address

def code_digest(code):
    return hmac.new(settings.SECRET_KEY.encode(), ("pos-pair:" + code).encode(), hashlib.sha256).hexdigest()

@transaction.atomic
def generate_code(branch, actor, register=None):
    Location.objects.select_for_update().get(pk=branch.pk)
    if not branch.active or branch.kind != "branch": raise ValidationError("Choose an active branch.")
    if register:
        register = Register.objects.select_for_update().get(pk=register.pk)
        if register.location_id != branch.pk or not register.active or register.token_hash or DeviceEnrollment.objects.filter(register=register).exists():
            raise ValidationError("Only an active, unpaired POS can receive a pairing code.")
    PairingCode.objects.filter(branch=branch, register=register, consumed_at__isnull=True).update(expires_at=timezone.now())
    while True:
        code = "".join(secrets.choice(ALPHABET) for _ in range(5))
        if not PairingCode.objects.filter(code_hash=code_digest(code)).exists(): break
    PairingCode.objects.create(branch=branch, register=register, created_by=actor, code_hash=code_digest(code), expires_at=timezone.now() + timedelta(minutes=10))
    return code

def enroll(identifier, digest, branch, actor, address="", register=None):
    existing = DeviceEnrollment.objects.select_related("register__location").filter(pk=identifier).first()
    if existing:
        if not hmac.compare_digest(existing.secret_hash, digest) or existing.register.location_id != branch.pk:
            raise ValidationError("This installation is already registered elsewhere.")
        return existing
    if register:
        register = Register.objects.select_for_update().get(pk=register.pk)
        if register.location_id != branch.pk or not register.active or register.token_hash or DeviceEnrollment.objects.filter(register=register).exists():
            raise ValidationError("This POS is already paired or disabled. Ask for a new code.")
    else:
        register = Register.objects.create(location=branch, code="pos-" + identifier.hex, name="POS " + identifier.hex[:6].upper())
    return DeviceEnrollment.objects.create(installation_id=identifier, register=register, secret_hash=digest, enrolled_by=actor, address_hint=address)

@transaction.atomic
def review_request(identifier, actor, approve, branch=None):
    Installation.objects.select_for_update().get(pk=1)
    item = EnrollmentRequest.objects.select_for_update().get(pk=identifier)
    if item.status != "pending" or item.expires_at <= timezone.now(): raise ValidationError("This request has already been reviewed or expired.")
    if approve:
        if branch is None:
            company = Company.objects.get()
            if Location.objects.filter(company=company, kind="branch", name__iexact=item.branch_name).exists():
                raise ValidationError("This branch name exists. Select the existing branch before approving this POS.")
            branch = Location.objects.create(company=company, name=item.branch_name, address=item.branch_address, code="branch-" + secrets.token_hex(5), kind="branch")
        if not branch.active or branch.kind != "branch": raise ValidationError("Choose an active branch.")
        enroll(item.installation_id, item.secret_hash, branch, actor, item.branch_address)
    item.status = "approved" if approve else "rejected"
    item.reviewed_by, item.reviewed_at = actor, timezone.now()
    item.save(update_fields=["status", "reviewed_by", "reviewed_at"])

@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([])
def enrollment(request):
    data = request.data
    try:
        if not isinstance(data, dict): raise ValueError()
        identifier = UUID(str(data.get("installation_id")))
        secret = data.get("installation_secret")
        if not isinstance(secret, str) or not 40 <= len(secret) <= 100: raise ValueError()
        digest = hashlib.sha256(secret.encode()).hexdigest()
        action = data.get("action", "status")
        if action not in {"status", "request", "pair"}: raise ValueError()
    except (ValueError, TypeError): return Response({"detail": "Invalid device request."}, status=400)
    limit = 90 if action == "status" else 10
    if not count_login_attempt(f"enroll:{action}:ip:{client_address(request)}", limit) or not count_login_attempt(f"enroll:{action}:device:{identifier}", limit):
        return Response({"detail": "Too many requests. Try again in five minutes."}, status=429)
    with transaction.atomic():
        installation = Installation.objects.select_for_update().filter(pk=1, completed_at__isnull=False).first()
        if not installation or not Company.objects.filter(active=True).exists(): return Response({"detail": "BackOffice setup is not complete."}, status=403)
        existing = DeviceEnrollment.objects.select_related("register__location").filter(pk=identifier).first()
        if existing:
            if not hmac.compare_digest(existing.secret_hash, digest): return Response({"detail": "Device identity does not match."}, status=403)
            if not existing.register.active or not existing.register.location.active: return Response({"detail": "This POS or branch is disabled."}, status=403)
            return Response({"status": "approved", "branch_name": existing.register.location.name, "branch_address": existing.register.location.address})
        pending = EnrollmentRequest.objects.filter(pk=identifier).first()
        if pending and not hmac.compare_digest(pending.secret_hash, digest): return Response({"detail": "Device identity does not match."}, status=403)
        if action == "pair":
            code = data.get("code", "")
            if not isinstance(code, str): return Response({"detail": "Enter a valid five-character code."}, status=400)
            item = PairingCode.objects.select_for_update().select_related("branch", "created_by").filter(code_hash=code_digest(code.strip().upper()), consumed_at__isnull=True, expires_at__gt=timezone.now(), branch__active=True).first()
            if not item: return Response({"detail": "Code is invalid, expired, or already used."}, status=403)
            try:
                enroll(identifier, digest, item.branch, item.created_by, register=item.register)
            except ValidationError as error:
                return Response({"detail": "; ".join(error.messages)}, status=403)
            item.consumed_at, item.installation_id = timezone.now(), identifier
            item.save(update_fields=["consumed_at", "installation_id"])
            if pending:
                pending.status, pending.reviewed_by, pending.reviewed_at = "approved", item.created_by, timezone.now()
                pending.save(update_fields=["status", "reviewed_by", "reviewed_at"])
            return Response({"status": "approved", "branch_name": item.branch.name, "branch_address": item.branch.address})
        if action == "request" and (not pending or pending.expires_at <= timezone.now()):
            name, address = data.get("branch_name", ""), data.get("branch_address", "")
            if not isinstance(name, str) or not 1 <= len(name.strip()) <= 150 or not isinstance(address, str) or len(address) > 300:
                return Response({"detail": "Enter a branch name and optional address."}, status=400)
            pending, _ = EnrollmentRequest.objects.update_or_create(pk=identifier, defaults={"secret_hash": digest, "branch_name": name.strip(), "branch_address": address.strip(), "status": "pending", "reviewed_by": None, "reviewed_at": None, "expires_at": timezone.now() + timedelta(hours=24)})
        return Response({"status": ("expired" if pending.expires_at <= timezone.now() else pending.status) if pending else "unregistered"})
