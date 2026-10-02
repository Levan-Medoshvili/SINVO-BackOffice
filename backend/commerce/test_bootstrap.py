from io import StringIO
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings


class InitialAdministratorTests(TestCase):
    def test_bootstrap_is_idempotent_and_does_not_print_password(self):
        password = 'test-only-initial-password-with-sufficient-length'
        output = StringIO()
        with patch.dict('os.environ', {'DJANGO_SUPERUSER_USERNAME': 'admin', 'DJANGO_SUPERUSER_PASSWORD': password}):
            call_command('bootstrap_admin', stdout=output)
        user = get_user_model().objects.get(username='admin')
        self.assertTrue(user.is_superuser and user.check_password(password))
        user.set_password('changed-by-administrator')
        user.save()
        with patch.dict('os.environ', {'DJANGO_SUPERUSER_PASSWORD': password}):
            call_command('bootstrap_admin', stdout=output)
        user.refresh_from_db()
        self.assertTrue(user.check_password('changed-by-administrator'))
        self.assertNotIn(password, output.getvalue())
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_bootstrap_cannot_promote_an_existing_username(self):
        user = get_user_model().objects.create_user(username='admin', password='existing')
        with patch.dict('os.environ', {'DJANGO_SUPERUSER_USERNAME': 'admin', 'DJANGO_SUPERUSER_PASSWORD': 'new-test-password-long-enough'}):
            with self.assertRaises(CommandError):
                call_command('bootstrap_admin', stdout=StringIO())
        user.refresh_from_db()
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.check_password('existing'))

    @override_settings(SIMPLEPOS_BUILD_REVISION='a' * 40)
    def test_health_identifies_the_deployed_revision(self):
        self.assertEqual(self.client.get('/healthz/').json()['build_revision'], 'a' * 40)
