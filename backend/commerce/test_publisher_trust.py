import io
import tempfile
from pathlib import Path
from unittest.mock import patch
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

class PublisherTrustTests(SimpleTestCase):
    def test_trust_is_bootstrapped_once_by_publisher_and_cannot_be_silently_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory)/'public.pem', Path(directory)/'config/public.pem'
            def public_key():
                return rsa.generate_private_key(public_exponent=65537,key_size=3072).public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
            source.write_bytes(public_key())
            with override_settings(SIMPLEPOS_RELEASE_PUBLIC_KEY=target), patch('os.geteuid', return_value=0):
                call_command('trust_cashier_publisher_key', str(source), stdout=io.StringIO())
                original = target.read_bytes()
                call_command('trust_cashier_publisher_key', str(source), stdout=io.StringIO())
                source.write_bytes(public_key())
                with self.assertRaises(CommandError): call_command('trust_cashier_publisher_key', str(source), stdout=io.StringIO())
                self.assertEqual(target.read_bytes(), original)
                with patch('os.geteuid', return_value=1000), self.assertRaises(CommandError):
                    call_command('trust_cashier_publisher_key', str(source), stdout=io.StringIO())
