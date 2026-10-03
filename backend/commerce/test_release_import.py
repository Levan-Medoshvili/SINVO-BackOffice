import base64
import hashlib
import io
import json
import subprocess
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from commerce.models import CashierRelease, Installation, UpdateRollout, UpdateDelivery


class ReleaseCommandTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.keys = tempfile.TemporaryDirectory()
        cls.private = Path(cls.keys.name) / 'private.pem'
        cls.public = Path(cls.keys.name) / 'public.pem'
        subprocess.run(['openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:3072', '-out', str(cls.private)], check=True, capture_output=True)
        subprocess.run(['openssl', 'pkey', '-in', str(cls.private), '-pubout', '-out', str(cls.public)], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.keys.cleanup()
        super().tearDownClass()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bundle = self.root / 'bundle'
        self.bundle.mkdir()
        self.releases = self.root / 'releases'
        override = override_settings(SIMPLEPOS_RELEASE_DIR=self.releases, SIMPLEPOS_RELEASE_PUBLIC_KEY=self.public)
        override.enable()
        self.addCleanup(override.disable)
        self.admin = get_user_model().objects.create_superuser('publisher', 'test-only-not-a-real-password')
        Installation.objects.update_or_create(pk=1, defaults={'completed_at': timezone.now()})
        self.write_bundle()

    def write_bundle(self, content=b'Test signed package', filename='SimplePOS-Cashier-0.4.1-win-x64.zip'):
        metadata = {'schema': 1, 'version': '0.4.1', 'platform': 'win-x64', 'filename': filename, 'size': len(content), 'sha256': hashlib.sha256(content).hexdigest()}
        manifest = self.bundle / 'manifest.json'
        manifest.write_text(json.dumps(metadata) + '\n')
        signature = subprocess.run(['openssl', 'dgst', '-sha256', '-sign', str(self.private), str(manifest)], check=True, capture_output=True).stdout
        (self.bundle / 'manifest.sig').write_bytes(base64.b64encode(signature) + b'\n')
        (self.bundle / filename).write_bytes(content)

    def publish(self, actor='publisher'):
        out = io.StringIO()
        call_command('import_cashier_release', str(self.bundle), actor=actor, stdout=out)
        return out.getvalue()

    def test_signed_publication_is_visible_and_retry_preserves_identity_without_rollout(self):
        self.assertIn('available in BackOffice: 0.4.1', self.publish())
        original = CashierRelease.objects.get()
        self.assertEqual(original.uploaded_by, self.admin)
        self.publish()
        self.assertEqual(CashierRelease.objects.get().pk, original.pk)
        self.assertFalse(UpdateRollout.objects.exists())
        self.assertFalse(UpdateDelivery.objects.exists())
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get('/cashier/releases/win-x64/versions/0.4.1/manifest.json').status_code, 200)
        # Rollout form reads the same release catalog, including CI imports.
        from backoffice.forms import RolloutForm
        self.assertIn(original, RolloutForm.base_fields['release'].queryset)

    def test_different_signed_package_cannot_replace_version(self):
        self.publish()
        digest = CashierRelease.objects.get().sha256
        self.write_bundle(b'Different but correctly signed package')
        with self.assertRaisesMessage(CommandError, 'different package already uses this version'):
            self.publish()
        self.assertEqual(CashierRelease.objects.get().sha256, digest)

    def test_wrong_key_and_corrupt_package_are_rejected(self):
        (self.bundle / 'manifest.sig').write_text(base64.b64encode(b'invalid signature').decode())
        with self.assertRaisesMessage(CommandError, 'signature does not match'):
            self.publish()
        self.write_bundle()
        archive = self.bundle / 'SimplePOS-Cashier-0.4.1-win-x64.zip'
        archive.write_bytes(b'x' * archive.stat().st_size)
        with self.assertRaisesMessage(CommandError, 'checksum does not match'):
            self.publish()
        self.assertFalse(CashierRelease.objects.exists())

    def test_publisher_must_be_existing_active_superuser(self):
        for username in ['missing', 'publisher']:
            if username == 'publisher':
                self.admin.is_active = False
                self.admin.save()
            with self.assertRaisesMessage(CommandError, 'active BackOffice superuser'):
                self.publish(username)
        self.admin.is_active = True
        self.admin.is_superuser = False
        self.admin.save()
        with self.assertRaises(CommandError):
            self.publish()

    def test_missing_key_and_invalid_bundle_paths_fail(self):
        with override_settings(SIMPLEPOS_RELEASE_PUBLIC_KEY=self.root / 'missing.pem'):
            with self.assertRaisesMessage(CommandError, 'trusted release public key'):
                self.publish()
        metadata = json.loads((self.bundle / 'manifest.json').read_text())
        metadata['filename'] = '../escape.zip'
        (self.bundle / 'manifest.json').write_text(json.dumps(metadata))
        with self.assertRaisesMessage(CommandError, 'Invalid package filename'):
            self.publish()
        self.write_bundle()
        archive = self.bundle / 'SimplePOS-Cashier-0.4.1-win-x64.zip'
        external = self.root / 'outside.zip'
        archive.rename(external)
        archive.symlink_to(external)
        with self.assertRaisesMessage(CommandError, 'regular files'):
            self.publish()

    def test_retry_detects_damaged_stored_files(self):
        self.publish()
        saved = self.releases / 'win-x64' / 'versions' / '0.4.1' / 'SimplePOS-Cashier-0.4.1-win-x64.zip'
        saved.write_bytes(b'corrupt')
        with self.assertRaisesMessage(CommandError, 'version files are damaged'):
            self.publish()
        self.assertEqual(CashierRelease.objects.count(), 1)
