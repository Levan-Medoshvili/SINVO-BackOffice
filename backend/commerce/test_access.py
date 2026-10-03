import uuid
import hashlib
from datetime import timedelta
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone
from rest_framework.test import APIClient
from .models import Company, Location, Product, Register, EmployeeAccess, AccessGroup, AccessPermission, DeviceEnrollment, LiveBasket, Installation
from .access import permission_codes
from .forms import EmployeeAccessForm, AccessGroupForm
from .supervision import request_removal
from .tests import make_operator


class EmployeeTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Company", code="co")
        self.branch = Location.objects.create(company=self.company, name="Store", code="store", kind="branch")
        self.other = Location.objects.create(company=self.company, name="Other", code="other", kind="branch")
        self.register = Register.objects.create(location=self.branch, code="pos", name="POS")
        self.user, self.access, self.operator = make_operator(self.register)
        self.client = APIClient()
        self.body = {"username": self.user.username, "password": "test-password", "branch_name": "Store", "branch_address": "Hint only", "installation_id": str(uuid.uuid4()), "installation_secret": "test-only-device-secret-" * 3}
    def signin(self): return self.client.post("/api/v1/cashier/sign-in/", self.body, format="json")

    def test_login_enrolls_once_and_retry_accepts_rotated_legacy_credential(self):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + self.register.issue_token())
        first = self.signin()
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["register"]["id"], str(self.register.pk))
        second = self.signin()
        self.assertEqual(second.status_code, 200)
        self.assertNotEqual(first.json()["register_credential"], second.json()["register_credential"])
        self.assertEqual(DeviceEnrollment.objects.count(), 1)
        self.assertEqual(Register.objects.count(), 1)
        self.branch.refresh_from_db()
        self.assertEqual(self.branch.address, "")
        self.body["installation_secret"] = "incorrect-secret-" * 4
        self.assertEqual(self.signin().status_code, 403)

    def test_login_checks_application_branch_and_active_status(self):
        DeviceEnrollment.objects.create(installation_id=self.body["installation_id"], register=self.register, secret_hash=hashlib.sha256(self.body["installation_secret"].encode()).hexdigest(), enrolled_by=self.user)
        self.access.all_branches = False
        self.access.save()
        self.access.branches.add(self.other)
        self.assertEqual(self.signin().status_code, 403)
        self.access.branches.add(self.branch)
        self.assertEqual(self.signin().status_code, 200)
        self.access.application = "backend"
        self.access.save()
        self.assertEqual(self.signin().status_code, 403)
        self.access.application = "both"
        self.access.save()
        self.assertEqual(self.signin().status_code, 200)
        self.user.is_active = False
        self.user.save()
        self.assertEqual(self.signin().status_code, 403)

    def test_group_permissions_are_additive_and_company_scoped(self):
        group = AccessGroup.objects.create(company=self.company, name="Cashiers")
        group.permissions.add(AccessPermission.objects.get(pk="remove_basket_line"))
        self.access.groups.add(group)
        self.access.permissions.add(AccessPermission.objects.get(pk="supervise_basket"))
        self.assertEqual(permission_codes(self.access), {"remove_basket_line", "supervise_basket"})
        company = Company(name="Foreign", code="foreign")
        with self.assertRaises(ValidationError):
            group.company = company
            group.save()
        branch = Location.objects.create(company=self.company, name="Warehouse", code="s", kind="warehouse")
        form = EmployeeAccessForm(data={"user": self.user.pk, "company": self.company.pk, "application": "cashier", "branches": [branch.pk]}, instance=self.access)
        self.assertFalse(form.is_valid())
        self.assertIn("branches", form.errors)
        self.assertFalse(AccessGroupForm(data={"company": company.pk, "name": "Invalid", "members": [self.access.pk]}).is_valid())

    @override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
    def test_signin_rate_limit(self):
        self.body["password"] = "wrong"
        for _ in range(10): self.assertEqual(self.signin().status_code, 403)
        self.assertEqual(self.signin().status_code, 429)

    def test_superuser_can_create_cashier_from_backoffice(self):
        admin = get_user_model().objects.create_superuser(username="admin", password="test-password")
        Installation.objects.update_or_create(pk=1, defaults={"completed_at": timezone.now()})
        self.client.force_login(admin)
        self.assertContains(self.client.get("/team/add/"), "Both")
        response = self.client.post("/team/add/", {"username":"new-cashier", "name":"New", "surname":"Employee", "password":"Strong-test-password-842!", "password_confirm":"Strong-test-password-842!", "application":"both", "all_branches":"on", "is_active":"on"})
        self.assertEqual(response.status_code, 302)
        employee = get_user_model().objects.get(username="new-cashier")
        self.assertTrue(employee.check_password("Strong-test-password-842!"))
        self.assertTrue(employee.is_staff)
        self.assertEqual(employee.pos_access.application, "both")


class SupervisionTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Company", code="co")
        self.branch = Location.objects.create(company=self.company, name="Store", code="store", kind="branch")
        self.product = Product.objects.create(company=self.company, home_location=self.branch, name="Milk", barcode="001", price_minor=450)
        self.register = Register.objects.create(location=self.branch, code="pos", name="POS")
        self.user, self.access, self.operator = make_operator(self.register)
        self.manager = get_user_model().objects.create_user(username="manager", password="test-password")
        access = EmployeeAccess.objects.create(user=self.manager, company=self.company, application="backend", all_branches=False)
        access.branches.add(self.branch)
        access.permissions.add(AccessPermission.objects.get(pk="supervise_basket"))
        self.manager.refresh_from_db()
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + self.register.issue_token())
        self.basket = {"id": str(uuid.uuid4()), "revision": 1, "state": "active", "authorization": self.operator["authorization"], "lines": [{"id": str(self.product.pk), "price_id": str(self.product.current_price_id), "key": f"{self.product.pk}:{self.product.current_price_id}", "quantity_milli": 1000, "price_minor": 450}]}
        self.assertEqual(self.sync().status_code, 200)
    def sync(self, acks=None): return self.client.post("/api/v1/basket/sync/", {"basket": self.basket, "acknowledgements": acks or []}, format="json")
    def remove(self): return request_removal(self.manager, self.register.pk, self.basket["id"], self.basket["revision"], self.basket["lines"][0]["key"], "Customer changed mind")
    def test_command_is_pending_until_device_ack_and_retry_is_idempotent(self):
        command = self.remove()
        self.assertEqual(command.status, "pending")
        self.assertEqual(len(self.sync().json()["commands"]), 1)
        self.assertIn("Milk", LiveBasket.objects.get().lines_json)
        ack = {"id": str(command.pk), "status": "applied", "detail": "Applied"}
        self.basket.update(revision=2, state="empty", lines=[])
        for _ in range(2): self.assertEqual(self.sync([ack]).json()["acknowledged"], [str(command.pk)])
        command.refresh_from_db()
        self.assertEqual(command.status, "applied")
        self.assertEqual(LiveBasket.objects.get().lines_json, "[]")
    def test_stale_paid_locked_and_unauthorized_baskets_cannot_be_removed(self):
        for state in ["locked", "completed"]:
            LiveBasket.objects.update(state=state)
            with self.assertRaises(ValidationError): self.remove()
        LiveBasket.objects.update(state="active", seen_at=timezone.now() - timedelta(seconds=16))
        with self.assertRaises(ValidationError): self.remove()
        LiveBasket.objects.update(seen_at=timezone.now())
        self.basket["revision"] = 2
        with self.assertRaises(ValidationError): self.remove()
        with self.assertRaises(PermissionDenied): request_removal(self.user, self.register.pk, self.basket["id"], 1, "any", "No access")
    def test_old_snapshot_cannot_overwrite_new_basket(self):
        self.basket["revision"] = 3
        self.assertEqual(self.sync().status_code, 200)
        self.basket["revision"] = 2
        self.assertEqual(self.sync().status_code, 409)
        self.assertEqual(LiveBasket.objects.get().revision, 3)
    def test_online_revocation_locks_basket(self):
        self.user.is_active = False
        self.user.save()
        self.assertTrue(self.sync().json()["access_denied"])
        self.assertEqual(LiveBasket.objects.get().state, "locked")
    def test_admin_branch_scope_and_csrf(self):
        Installation.objects.update_or_create(pk=1, defaults={"completed_at": timezone.now()})
        self.client.credentials()
        self.client.force_login(self.manager)
        url = f"/checkouts/{self.register.pk}/"
        self.assertContains(self.client.get(url, follow=True), "Milk")
        self.assertEqual(self.client.get("/team/").status_code, 403)
        self.manager.pos_access.branches.clear()
        self.assertEqual(self.client.get(url).status_code, 404)
        guarded = APIClient(enforce_csrf_checks=True)
        guarded.force_login(self.manager)
        self.assertEqual(guarded.post(f"/checkouts/{self.register.pk}/", {}).status_code, 403)


class ReleaseDeliveryTests(TestCase):
    def test_feed_serves_only_published_files_and_rejects_traversal_and_symlinks(self):
        import json, tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "releases"
            platform = root / "win-x64"
            platform.mkdir(parents=True)
            (platform / "manifest.json").write_text(json.dumps({"filename": "Cashier.zip"}))
            (platform / "manifest.sig").write_text("test-only-signature")
            (platform / "Cashier.zip").write_bytes(b"test-archive")
            (platform / "not-published.zip").write_bytes(b"not-public")
            secret = Path(directory) / "private.txt"
            secret.write_text("private")
            (platform / "escape.zip").symlink_to(secret)
            with override_settings(SIMPLEPOS_RELEASE_DIR=root):
                response = self.client.get("/cashier/releases/win-x64/Cashier.zip")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(b"".join(response.streaming_content), b"test-archive")
                response.close()
                for filename in ["not-published.zip", "escape.zip", "../private.txt", "private.pem"]:
                    self.assertEqual(self.client.get("/cashier/releases/win-x64/" + filename).status_code, 404)
                self.assertEqual(self.client.post("/cashier/releases/win-x64/manifest.json").status_code, 405)
