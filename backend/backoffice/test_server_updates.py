from unittest.mock import patch
from django.test import TestCase
from django.contrib.auth import get_user_model
from commerce.models import Company, Installation

class SoftwareUpdateUITests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("updater-admin", "test@example.test", "password-very-long-123!")
        Company.objects.create(name="Test Company", code="test-company")
        Installation.objects.create(pk=1, completed_at="2026-10-10T00:00:00Z")
        self.client.force_login(self.admin)

    def test_update_page_does_not_install(self):
        response=self.client.get("/system-updates/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Check for updates")
        self.assertContains(response, "Update now")

    def test_no_identity_cannot_trigger_update(self):
        with patch("backoffice.server_updates._identity", return_value=None):
            response=self.client.post("/system-updates/check/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "unconfigured")
