import hashlib
import uuid
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase, Client, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from commerce.models import (Company, Installation, Location, Product, StockItem, StockMovement,
    EmployeeAccess, AccessPermission, AccessGroup, DeviceEnrollment, EnrollmentRequest, PairingCode, Register)
from commerce.enrollment import generate_code, review_request

PASSWORD = 'Test-only-long-secret-523!'


@override_settings(SIMPLEPOS_SETUP_TOKEN='test-only-setup-token-more-than-24-characters')
class SetupTests(TestCase):
    data = {'name':'Test Stores', 'name_ka':'ტესტი', 'email':'owner@example.test', 'username':'owner',
        'password':PASSWORD, 'password_confirm':PASSWORD, 'address':'Tbilisi'}

    def unlock(self, client=None):
        return (client or self.client).post('/setup/', {'setup_key':'test-only-setup-token-more-than-24-characters'})

    def test_first_start_creates_one_company_and_owner_once(self):
        self.assertRedirects(self.client.get('/'), '/setup/', fetch_redirect_response=False)
        self.client.post('/setup/', self.data)
        self.assertFalse(Company.objects.exists())
        self.assertEqual(self.unlock().status_code, 302)
        response = self.client.post('/setup/', self.data)
        self.assertRedirects(response, '/login/')
        company, owner = Company.objects.get(), get_user_model().objects.get()
        self.assertEqual(company.name_ka, 'ტესტი')
        self.assertTrue(owner.check_password(PASSWORD))
        self.assertEqual(owner.pos_access.application, 'both')
        self.assertNotIn('_auth_user_id', self.client.session)
        self.client.post('/setup/', {**self.data, 'name':'Replacement'})
        self.assertEqual(Company.objects.get().name, 'Test Stores')
        self.assertIsNotNone(Installation.objects.get(pk=1).completed_at)

    def test_required_fields_and_csrf(self):
        self.unlock()
        bad = self.data.copy(); bad.pop('name_ka'); bad.pop('email')
        response = self.client.post('/setup/', bad)
        self.assertIn('name_ka', response.context['form'].errors)
        self.assertIn('email', response.context['form'].errors)
        self.assertFalse(Company.objects.exists())
        self.assertEqual(Client(enforce_csrf_checks=True).post('/setup/', self.data).status_code, 403)

    def test_stale_unlocked_browser_cannot_replace_owner_and_singleton_is_db_enforced(self):
        other = Client(); self.unlock(other); self.unlock()
        self.client.post('/setup/', self.data)
        other.post('/setup/', {**self.data, 'username':'another'})
        self.assertEqual(get_user_model().objects.count(), 1)
        for slot in [1, 2]:
            with self.assertRaises(IntegrityError), transaction.atomic():
                Company.objects.create(name='Forbidden', code='second', installation_slot=slot)


class BackOfficeTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='Test Stores', name_ka='ტესტი', code='test')
        Installation.objects.update_or_create(pk=1, defaults={'completed_at':timezone.now()})
        self.owner = get_user_model().objects.create_superuser('owner', PASSWORD, name='Levan', surname='Test')
        EmployeeAccess.objects.create(user=self.owner, company=self.company, application='both', all_branches=True)
        self.branch = Location.objects.create(company=self.company, code='vake', name='Vake', kind='branch')
        self.client.force_login(self.owner)

    def test_custom_screens_and_old_admin_disabled(self):
        for url in ['/', '/company/', '/password/', '/team/', '/team/add/', '/sales/', '/checkouts/'] + [f'/manage/{section}/' for section in ['branches','warehouses','products','categories','stock','groups','registers']]:
            with self.subTest(url=url): self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.get('/admin/commerce/company/add/').status_code, 404)
        self.assertEqual(self.client.get('/manage/companies/add/').status_code, 404)
        self.client.post('/i18n/setlang/', {'language':'ka', 'next':'/'})
        self.assertContains(self.client.get('/'), 'მიმოხილვა')

    def test_product_creation_audits_opening_stock_and_prices_remain_immutable(self):
        data = {'name':'Milk', 'barcode':'0001', 'home_location':self.branch.pk, 'unit':'piece', 'price':'4.50', 'opening_quantity':'100', 'active':'on'}
        self.assertEqual(self.client.post('/manage/products/add/', data).status_code, 302)
        product = Product.objects.get()
        original = product.current_price_id
        self.assertEqual(StockItem.objects.get().quantity_milli, 100000)
        self.assertEqual(StockMovement.objects.get().actor, self.owner)
        self.assertEqual(self.client.post(f'/manage/products/{product.pk}/', {**data, 'price':'5.00'}).status_code, 302)
        product.refresh_from_db()
        self.assertNotEqual(product.current_price_id, original)
        self.assertEqual(product.prices.get(pk=original).price_minor, 450)
        response = self.client.post('/manage/products/add/', {**data, 'barcode':'0002', 'opening_quantity':'1.5'})
        self.assertIn('opening_quantity', response.context['form'].errors)
        self.assertEqual(Product.objects.count(), 1)

    def test_backend_application_and_permission_gates(self):
        user = get_user_model().objects.create_user('employee', PASSWORD)
        access = EmployeeAccess.objects.create(user=user, company=self.company, application='cashier', all_branches=True)
        self.client.force_login(user)
        self.assertEqual(self.client.get('/').status_code, 403)
        access.application = 'backend'; access.save(); user.refresh_from_db()
        self.client.force_login(user)
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertEqual(self.client.post('/manage/branches/add/', {'name':'No', 'code':'no'}).status_code, 403)
        self.assertEqual(self.client.get('/team/').status_code, 403)
        access.permissions.add(AccessPermission.objects.get(pk='manage_catalog'))
        self.assertEqual(self.client.get('/manage/products/').status_code, 200)
        self.assertEqual(self.client.get('/sales/').status_code, 403)

    def test_users_groups_branches_and_owner_protection(self):
        group = AccessGroup.objects.create(company=self.company, name='Cashiers')
        group.permissions.add(AccessPermission.objects.get(pk='remove_basket_line'))
        data = {'username':'cashier', 'application':'cashier', 'branches':[self.branch.pk], 'groups':[group.pk], 'is_active':'on', 'password':PASSWORD, 'password_confirm':PASSWORD}
        self.assertEqual(self.client.post('/team/add/', data).status_code, 302)
        user = get_user_model().objects.get(username='cashier')
        self.assertFalse(user.is_staff)
        self.assertEqual(list(user.pos_access.branches.all()), [self.branch])
        self.assertEqual(list(user.pos_access.groups.all()), [group])
        self.assertNotIn('company', self.client.get('/team/add/').context['form'].fields)
        response = self.client.post(f'/team/{self.owner.pk}/', {'username':'owner', 'application':'cashier'})
        self.assertTrue(response.context['form'].non_field_errors())
        self.owner.refresh_from_db(); self.assertTrue(self.owner.is_active)

    def test_mutations_require_csrf(self):
        guarded = Client(enforce_csrf_checks=True); guarded.force_login(self.owner)
        for url in [f'/branches/{self.branch.pk}/pair/', '/manage/products/add/', '/team/add/', '/company/']:
            self.assertEqual(guarded.post(url, {}).status_code, 403)


class EnrollmentTests(TestCase):
    def setUp(self):
        BackOfficeTests.setUp(self)
        self.api = APIClient()
        self.identity = {'installation_id':str(uuid.uuid4()), 'installation_secret':'test-only-device-secret-'*3}

    def send(self, action, **data):
        return self.api.post('/api/v1/cashier/enrollment/', {**self.identity, 'action':action, **data}, format='json')

    def signin(self, branch):
        return self.api.post('/api/v1/cashier/sign-in/', {**self.identity, 'branch_name':branch, 'username':'owner', 'password':PASSWORD}, format='json')

    def test_pending_request_requires_approval_before_login(self):
        self.assertEqual(self.send('request', branch_name='New Store', branch_address='Tbilisi').json()['status'], 'pending')
        self.assertEqual(Location.objects.count(), 1)
        self.assertEqual(self.signin('New Store').status_code, 403)
        request = EnrollmentRequest.objects.get()
        response = self.client.post(f'/enrollment/{request.pk}/', {'decision':'approve'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Location.objects.count(), 2)
        self.assertEqual(self.send('status').json()['status'], 'approved')
        self.assertEqual(self.signin('New Store').status_code, 200)
        branch = Location.objects.get(name='New Store'); branch.name='Renamed'; branch.save()
        self.assertEqual(self.signin('New Store').json()['branch']['name'], 'Renamed')

    def test_code_is_hashed_single_use_and_device_retry_is_idempotent(self):
        code = generate_code(self.branch, self.owner)
        self.assertRegex(code, r'^[A-Z2-9]{5}$')
        self.assertNotIn(code, PairingCode.objects.get().code_hash)
        self.assertEqual(self.send('pair', code=code).json()['status'], 'approved')
        self.assertEqual(self.send('pair', code=code).json()['status'], 'approved')
        self.assertEqual(Register.objects.count(), 1)
        self.assertEqual(self.api.get('/api/v1/catalog/').status_code, 401)
        self.identity['installation_id']=str(uuid.uuid4())
        self.assertEqual(self.send('pair', code=code).status_code, 403)
        self.assertEqual(self.send('pair', code='XXXXX').status_code, 403)

    def test_rejection_secret_proof_existing_branch_and_expiry(self):
        self.send('request', branch_name='Vake')
        review_request(self.identity['installation_id'], self.owner, False)
        self.assertEqual(self.send('request', branch_name='Vake').json()['status'], 'rejected')
        old = self.identity['installation_secret']; self.identity['installation_secret']='different-secret-'*4
        self.assertEqual(self.send('status').status_code, 403)
        self.identity['installation_secret']=old
        EnrollmentRequest.objects.update(expires_at=timezone.now()-timedelta(seconds=1))
        self.send('request', branch_name='Vake')
        review_request(self.identity['installation_id'], self.owner, True, self.branch)
        self.assertEqual(Location.objects.count(), 1)
        self.assertEqual(self.send('status').json()['branch_name'], 'Vake')
        self.identity['installation_id']=str(uuid.uuid4())
        code = generate_code(self.branch, self.owner)
        PairingCode.objects.update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.send('pair', code=code).status_code, 403)

    def test_new_code_revokes_old_and_guessing_is_bounded(self):
        old = generate_code(self.branch, self.owner)
        current = generate_code(self.branch, self.owner)
        self.assertNotEqual(old, current)
        self.assertEqual(self.send('pair', code=old).status_code, 403)
        for _ in range(9): self.assertEqual(self.send('pair', code='XXXXX').status_code, 403)
        self.assertEqual(self.send('pair', code=current).status_code, 429)
