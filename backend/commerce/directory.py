"""Explicitly provisioned AD identities, certificate-verified LDAPS, local POS roles."""
import re
import ssl
from uuid import UUID
import ldap3
from ldap3.core.exceptions import LDAPException
from ldap3.utils.conv import escape_filter_chars
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.core.exceptions import PermissionDenied, ValidationError
from .integration_secrets import decrypt
from .models import DirectoryIdentity

ATTRIBUTES = ['objectGUID', 'userPrincipalName', 'sAMAccountName', 'givenName', 'sn', 'mail', 'userAccountControl']

def connect(config, user, password):
    if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?', config.host) or not password:
        raise ValidationError('Check the directory hostname and credentials.')
    tls = ldap3.Tls(validate=ssl.CERT_REQUIRED, ca_certs_data=config.ca_certificate or None,
                    valid_names=[config.host])
    server = ldap3.Server(config.host, port=config.port, use_ssl=True, tls=tls, connect_timeout=5)
    try:
        return ldap3.Connection(server, user=user, password=password, auto_bind=True, auto_referrals=False,
            receive_timeout=8, raise_exceptions=True)
    except (LDAPException, OSError, ValueError):
        raise ValidationError('Active Directory could not be reached or rejected the credentials. Check LDAPS, certificate trust and account access.') from None

def lookup(config, *, username=None, guid=None):
    if not config.enabled: raise ValidationError('Enable Active Directory first.')
    if guid:
        escaped = ''.join(f'\\{b:02x}' for b in UUID(str(guid)).bytes_le)
        clause = f'(objectGUID={escaped})'
    else:
        safe = escape_filter_chars(username or '')
        clause = f'(|(userPrincipalName={safe})(sAMAccountName={safe}))'
    connection = connect(config, config.bind_user, decrypt(config.password_encrypted))
    try:
        connection.search(config.base_dn, f'(&(objectClass=user)(!(objectClass=computer)){clause})',
            attributes=ATTRIBUTES, size_limit=2, time_limit=5)
        if connection.result.get('result') != 0 or len(connection.entries) != 1:
            raise ValidationError('Find one enabled AD user by exact sign-in name.')
        entry = connection.entries[0]
        values = entry.entry_attributes_as_dict
        def first(key):
            value = values.get(key, [])
            return value[0] if isinstance(value, list) and value else value if not isinstance(value, list) else ''
        if int(first('userAccountControl') or 0) & 2: raise ValidationError('This Active Directory user is disabled.')
        guid_value = first('objectGUID')
        guid_value = UUID(bytes_le=guid_value) if isinstance(guid_value, bytes) else UUID(str(guid_value).strip('{}'))
        upn = str(first('userPrincipalName'))
        if not upn or len(upn) > 150: raise ValidationError('The AD user needs a userPrincipalName of at most 150 characters.')
        return {'guid': str(guid_value), 'username': upn, 'name': str(first('givenName'))[:255],
                'surname': str(first('sn'))[:255], 'email': str(first('mail'))[:254], 'dn': entry.entry_dn}
    except (LDAPException, OSError, ValueError):
        raise ValidationError('Directory search failed. Check the base DN and service account permissions.') from None
    finally: connection.unbind()


class DirectoryBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        identity = DirectoryIdentity.objects.select_related('user', 'integration').filter(user__username__iexact=username or '').first()
        if not identity: return None
        if not identity.user.is_active or not identity.integration.enabled or not password: raise PermissionDenied()
        try:
            person = lookup(identity.integration, guid=identity.object_guid)
            connection = connect(identity.integration, person['dn'], password)
            connection.unbind()
        except ValidationError: raise PermissionDenied() from None
        return identity.user

    def get_user(self, user_id):
        user = super().get_user(user_id)
        return user if user and DirectoryIdentity.objects.filter(user=user, integration__enabled=True).exists() else None


class LocalBackend(ModelBackend):
    def user_can_authenticate(self, user):
        return not DirectoryIdentity.objects.filter(user=user).exists() and super().user_can_authenticate(user)
