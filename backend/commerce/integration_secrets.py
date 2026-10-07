"""Integration passwords are encrypted at rest with an installation-specific key."""
import base64
import hashlib
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ValidationError

def cipher():
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(('simplepos-integrations-v1:' + settings.SECRET_KEY).encode()).digest()))

def encrypt(value):
    return cipher().encrypt(value.encode()).decode()

def decrypt(value):
    try: return cipher().decrypt(value.encode()).decode()
    except (InvalidToken, ValueError): raise ValidationError('Re-enter the integration password in Settings.') from None
