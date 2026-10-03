import copy
import uuid
from pathlib import Path
from django.test import TestCase, SimpleTestCase, override_settings
from django.core.exceptions import ValidationError, ImproperlyConfigured
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient
from config.database import database_config
from datetime import timedelta
from .access import operator_data
from .models import EmployeeAccess, CashierSession
from .models import Company, Location, Product, Register, StockItem, StockAdjustment, Sale, StockMovement


def make_operator(register):
    user = get_user_model().objects.create_user(username="cashier-" + uuid.uuid4().hex[:8], password="test-password", name="Cashier", surname="Test")
    access = EmployeeAccess.objects.create(user=user, company=register.location.company, application="cashier", all_branches=True)
    session = CashierSession.objects.create(user=user, register=register, expires_at=timezone.now() + timedelta(days=7))
    return user, access, operator_data(session)


class DatabaseSelectionTests(SimpleTestCase):
    def test_all_three_engines(self):
        env = {"DB_NAME": "pos", "DB_USER": "test", "DB_PASSWORD": "test", "DB_HOST": "db"}
        for name, driver in [("postgres", "django.db.backends.postgresql"), ("mysql", "django.db.backends.mysql"), ("mssql", "mssql")]:
            with self.subTest(name=name):
                config = database_config({**env, "DB_ENGINE": name}, Path("/tmp"))
                self.assertEqual(config["ENGINE"], driver)
                self.assertNotIn("sqlite", config["ENGINE"])
        self.assertIn("TrustServerCertificate=no", database_config({**env, "DB_ENGINE": "mssql"}, Path("/tmp"))["OPTIONS"]["extra_params"])

    def test_no_silent_database_fallback(self):
        for env in [{"DB_ENGINE": "unknown"}, {"DB_ENGINE": "sqlite"}, {"DB_ENGINE": "postgres"}]:
            with self.assertRaises(ImproperlyConfigured):
                database_config(env, Path("/tmp"))


class CheckoutTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="One", code="one")
        self.location = Location.objects.create(company=self.company, code="store", name="Store", kind="branch")
        self.product = Product.objects.create(company=self.company, home_location=self.location, name="Milk", barcode="001", price_minor=450)
        self.stock = StockItem.objects.get(product=self.product, location=self.location)
        StockAdjustment.objects.create(stock_item=self.stock, quantity_milli=10000, reason="Opening")
        self.register = Register.objects.create(location=self.location, code="r1", name="Register")
        self.user, self.access, self.operator = make_operator(self.register)
        self.token = self.register.issue_token()
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + self.token)

    def payload(self):
        return {"id": str(uuid.uuid4()), "cashier_authorization": self.operator["authorization"], "occurred_at": timezone.now().isoformat(), "currency": "GEL", "payment_method": "cash",
            "cash_received_minor": 1000, "total_minor": 900, "lines": [{"product_id": str(self.product.pk),
            "price_id": str(self.product.current_price_id), "quantity_milli": 2000, "unit_price_minor": 450, "total_minor": 900}]}

    def send(self, payload):
        response = self.client.post("/api/v1/sales/", {"sales": [payload]}, format="json")
        self.assertEqual(response.status_code, 200)
        return response.json()["results"][0]

    def test_unsigned_legacy_sales_require_explicit_recovery_setting(self):
        payload = self.payload()
        del payload["cashier_authorization"]
        self.assertEqual(self.send(payload)["status"], "rejected")
        with override_settings(SIMPLEPOS_ALLOW_LEGACY_SALES=True): self.assertEqual(self.send(payload)["status"], "acknowledged")
        self.assertIsNone(Sale.objects.get().cashier_id)
        self.assertTrue(self.send(payload)["duplicate"])
    def test_tampered_cashier_grants_do_not_record_sales(self):
        payload = self.payload()
        payload["cashier_authorization"] += "tampered"
        self.assertEqual(self.send(payload)["status"], "rejected")
        self.assertFalse(Sale.objects.exists())
    def test_historical_offline_sale_preserves_cashier_after_revocation(self):
        payload = self.payload()
        self.user.is_active = False
        self.user.save()
        self.assertEqual(self.send(payload)["status"], "acknowledged")
        self.assertEqual(Sale.objects.get().cashier_id, self.user.pk)

    def test_retry_acknowledges_once_and_preserves_stock(self):
        payload = self.payload()
        self.assertFalse(self.send(payload)["duplicate"])
        self.assertTrue(self.send(payload)["duplicate"])
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity_milli, 8000)
        self.assertEqual(Sale.objects.count(), 1)
        self.assertEqual(StockMovement.objects.filter(reason="cash_sale").count(), 1)

    def test_same_id_different_contents_is_conflict(self):
        payload = self.payload()
        self.send(payload)
        payload["cash_received_minor"] += 100
        self.assertEqual(self.send(payload)["status"], "conflict")
        self.assertEqual(Sale.objects.count(), 1)

    def test_rejects_price_tampering_and_invalid_quantities_atomically(self):
        for key, value in [("quantity_milli", -1000), ("quantity_milli", True), ("quantity_milli", 1500), ("unit_price_minor", 1)]:
            payload = self.payload()
            payload["lines"][0][key] = value
            self.assertEqual(self.send(payload)["status"], "rejected")
        bad = self.payload()
        bad["lines"].append({**bad["lines"][0], "product_id": str(uuid.uuid4())})
        self.assertEqual(self.send(bad)["status"], "rejected")
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity_milli, 10000)
        self.assertEqual(Sale.objects.count(), 0)

    def test_cached_price_remains_acceptable_after_price_change(self):
        payload = self.payload()
        self.product.price_minor = 500
        self.product.save()
        self.assertEqual(self.send(payload)["status"], "acknowledged")
        self.assertEqual(Sale.objects.get().lines.get().unit_price_minor, 450)
        self.assertEqual(self.client.get("/api/v1/catalog/").json()["products"][0]["price_minor"], 500)

    def test_installation_rejects_second_company(self):
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError), transaction.atomic():
            Company.objects.create(name="Two", code="two")

    def test_other_branch_cannot_sell_unassigned_product(self):
        branch = Location.objects.create(company=self.company, code="another", name="Other", kind="branch")
        register = Register.objects.create(location=branch, code="r2", name="Other")
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + register.issue_token())
        self.assertEqual(self.send(self.payload())["status"], "rejected")

    def test_revoked_register_cannot_sync(self):
        self.register.issue_token()
        self.assertEqual(self.client.get("/api/v1/catalog/").status_code, 401)
        self.client.credentials()
        self.assertEqual(self.client.get("/api/v1/catalog/").status_code, 401)

    def test_adjustments_cannot_be_rewritten(self):
        adjustment = StockAdjustment.objects.get()
        adjustment.quantity_milli = 5
        with self.assertRaises(ValidationError): adjustment.save()

    def test_legacy_urls_disabled_and_staff_cannot_enter_platform_admin(self):
        self.assertEqual(self.client.get("/users/").status_code, 404)
        staff = get_user_model().objects.create_user(username="staff", password="test-password", is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get("/admin/").status_code, 302)

    def test_identity_changes_cannot_reassign_historical_stock_or_sales(self):
        other = Company(name="Other", code="other")
        branch = Location.objects.create(company=self.company, code="branch2", name="Other branch", kind="branch")
        for obj, field, value in [(self.location, "company", other), (self.product, "unit", "kg"), (self.register, "location", branch), (self.stock, "location", branch)]:
            old = getattr(obj, field)
            setattr(obj, field, value)
            with self.assertRaises(ValidationError): obj.save()
            setattr(obj, field, old)


from concurrent.futures import ThreadPoolExecutor
from django.db import connections, close_old_connections
from django.test import TransactionTestCase, skipUnlessDBFeature
from .services import receive_sale


class ConcurrentCheckoutTests(TransactionTestCase):
    @skipUnlessDBFeature("has_select_for_update")
    def test_concurrent_retry_posts_once(self):
        company = Company.objects.create(name="Concurrency", code="concurrency")
        location = Location.objects.create(company=company, code="s", kind="branch", name="Store")
        product = Product.objects.create(company=company, home_location=location, name="Milk", barcode="001", price_minor=450)
        register = Register.objects.create(location=location, code="r", name="POS")
        _, _, operator = make_operator(register)
        payload = {"id": str(uuid.uuid4()), "cashier_authorization": operator["authorization"], "occurred_at": timezone.now().isoformat(), "currency": "GEL", "payment_method": "cash",
            "cash_received_minor": 500, "total_minor": 450, "lines": [{"product_id": str(product.pk), "price_id": str(product.current_price_id),
            "quantity_milli": 1000, "unit_price_minor": 450, "total_minor": 450}]}
        def upload(_):
            close_old_connections()
            try:
                current = Register.objects.select_related("location__company").get(pk=register.pk)
                return receive_sale(current, payload)[1]
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            duplicates = list(pool.map(upload, range(2)))
        self.assertEqual(sorted(duplicates), [False, True])
        self.assertEqual(Sale.objects.count(), 1)
        self.assertEqual(StockMovement.objects.filter(reason="cash_sale").count(), 1)
        self.assertEqual(StockItem.objects.get(product=product).quantity_milli, -1000)
