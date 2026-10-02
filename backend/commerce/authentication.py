import hashlib
import hmac
from uuid import UUID
from django.contrib.auth.models import AnonymousUser
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import BasePermission
from .models import Register


class RegisterAuthentication(BaseAuthentication):
    def authenticate(self, request):
        parts = get_authorization_header(request).split()
        if not parts:
            return None
        if len(parts) != 2 or parts[0].lower() != b"bearer":
            raise AuthenticationFailed("Invalid register credential.")
        try:
            identifier, secret = parts[1].decode("ascii").split(".", 1)
            register = Register.objects.select_related("location__company").get(pk=UUID(identifier))
        except (ValueError, UnicodeError, Register.DoesNotExist):
            raise AuthenticationFailed("Invalid register credential.") from None
        if not register.token_hash or not hmac.compare_digest(register.token_hash, hashlib.sha256(secret.encode()).hexdigest()):
            raise AuthenticationFailed("Invalid register credential.")
        if not (register.active and register.location.active and register.location.company.active):
            raise AuthenticationFailed("Register access is disabled.")
        Register.objects.filter(pk=register.pk).update(last_seen=timezone.now())
        return AnonymousUser(), register

    def authenticate_header(self, request):
        return "Bearer"


class IsRegister(BasePermission):
    def has_permission(self, request, view):
        return isinstance(request.auth, Register)
