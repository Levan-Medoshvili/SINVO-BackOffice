"""Invoked by the authenticated publisher deployment, never by the customer UI."""
import os
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

class Command(BaseCommand):
    help = 'Install the publisher verification key once; reject implicit key replacement.'
    def add_arguments(self, parser): parser.add_argument('public_key')
    def handle(self, *args, **options):
        if not hasattr(os, 'geteuid') or os.geteuid() != 0: raise CommandError('Run through the trusted root publisher deployment.')
        source = Path(options['public_key'])
        if source.is_symlink() or not source.is_file() or source.stat().st_size > 16000: raise CommandError('Invalid publisher verification file.')
        try:
            key = serialization.load_pem_public_key(source.read_bytes())
            if not isinstance(key, rsa.RSAPublicKey) or key.key_size < 3072: raise ValueError()
            pem = key.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        except ValueError: raise CommandError('Use an RSA public key of at least 3072 bits.') from None
        target = settings.SIMPLEPOS_RELEASE_PUBLIC_KEY
        if target.is_symlink(): raise CommandError('Publisher verification path must not be a symlink.')
        if target.exists():
            try: existing = serialization.load_pem_public_key(target.read_bytes())
            except ValueError: raise CommandError('The existing publisher key needs operator review.') from None
            if existing.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo) != pem:
                raise CommandError('Publisher key differs from the configured key. Use the original publisher key; automatic replacement is blocked.')
        else:
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
            with target.open('xb') as output:
                output.write(pem)
                output.flush(); os.fsync(output.fileno())
                os.fchmod(output.fileno(), 0o644)
        self.stdout.write('Publisher verification is configured.')
