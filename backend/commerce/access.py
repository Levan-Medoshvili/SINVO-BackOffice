"""Server-side employee scope and bounded offline cashier authorizations."""
import hashlib
from datetime import timedelta
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from .models import EmployeeAccess, CashierSession, LoginRateBucket

SALT = "simplepos.cashier.authorization.v2"


def employee_access(user):
    if not user or not user.is_active: return None
    return EmployeeAccess.objects.select_related("company").filter(user=user, company__active=True).first()


def permission_codes(access):
    return set(access.permissions.values_list("code", flat=True)) | set(
        access.groups.filter(company=access.company).values_list("permissions__code", flat=True)) - {None}


def branch_allowed(access, branch):
    return bool(access and branch.active and branch.kind == "branch" and access.company_id == branch.company_id
        and (access.all_branches or access.branches.filter(pk=branch.pk).exists()))


def can_supervise(user, branch=None):
    if user.is_active and user.is_superuser: return True
    access = employee_access(user)
    return bool(access and access.application in {"backend", "both"} and "supervise_basket" in permission_codes(access)
        and (branch is None or branch_allowed(access, branch)))


def backend_allowed(user):
    if not user.is_active or not user.is_staff: return False
    if user.is_superuser: return True
    access = employee_access(user)
    return bool(access and access.application in {"backend", "both"})


def operator_data(session):
    access = employee_access(session.user)
    if not access or access.application not in {"cashier", "both"} or not branch_allowed(access, session.register.location):
        raise PermissionDenied("Cashier access is not permitted at this branch.")
    if session.ended_at or session.expires_at <= timezone.now():
        raise PermissionDenied("Sign in again.")
    data = {"session_id": str(session.pk), "user_id": str(session.user_id), "username": session.user.username,
        "name": session.user.name or session.user.username, "company_id": str(access.company_id),
        "branch_id": str(session.register.location_id), "register_id": str(session.register_id),
        "permissions": sorted(permission_codes(access)), "issued_at": session.created_at.isoformat(),
        "expires_at": session.expires_at.isoformat()}
    data["authorization"] = signing.dumps(data, salt=SALT, compress=True)
    return data


def decode_authorization(token, register, occurred_at=None):
    try:
        if not isinstance(token, str) or len(token) > 8000: raise ValueError()
        data = signing.loads(token, salt=SALT)
        if not isinstance(data, dict): raise ValueError()
        session = CashierSession.objects.select_related("user", "register__location__company").get(pk=data["session_id"], register=register, user_id=data["user_id"])
        if data["register_id"] != str(register.pk) or data["branch_id"] != str(register.location_id) or data["company_id"] != str(register.location.company_id):
            raise ValueError()
        at = occurred_at or timezone.now()
        if not (session.created_at - timedelta(minutes=5) <= at <= session.expires_at): raise ValueError()
        if at > timezone.now() + timedelta(minutes=5): raise ValueError()
        if session.ended_at and at > session.ended_at + timedelta(minutes=5): raise ValueError()
        if timezone.now() > session.expires_at + timedelta(days=30): raise ValueError()
        return session
    except (signing.BadSignature, CashierSession.DoesNotExist, ValueError, TypeError, KeyError):
        raise PermissionDenied("Cashier authorization is invalid or expired; retain the sale for review.") from None


@transaction.atomic
def count_login_attempt(key, limit):
    now = timezone.now()
    window = int(now.timestamp()) // 300
    digest = hashlib.sha256(f"{key}:{window}".encode()).hexdigest()
    bucket, _ = LoginRateBucket.objects.get_or_create(key=digest, defaults={"expires_at": now + timedelta(minutes=10)})
    bucket = LoginRateBucket.objects.select_for_update().get(pk=bucket.pk)
    bucket.attempts += 1
    bucket.save(update_fields=["attempts"])
    # Small rolling table; no credentials or usernames are retained in these keys.
    LoginRateBucket.objects.filter(expires_at__lt=now).delete()
    return bucket.attempts <= limit
