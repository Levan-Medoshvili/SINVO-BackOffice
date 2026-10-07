import base64
import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock
from uuid import uuid4
from xml.etree import ElementTree

from django.contrib.auth import authenticate, get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .catalog_import import parse_upload, apply_import, HEADERS, EXAMPLES
from .directory import lookup
from .integration_secrets import encrypt, decrypt
from .models import (Company, Installation, Category, Product, Location, StockItem, StockMovement,
    RSIntegration, DirectoryIntegration, DirectoryIdentity, Register, EmployeeAccess, AccessPermission, ReceivedWaybill)
from .rs_ge import RSClient, parse_xml, stage, receive


class Workspace(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='Example shop', code='example')
        Installation.objects.update_or_create(pk=1, defaults={'completed_at':timezone.now()})
        self.admin = get_user_model().objects.create_superuser('owner', 'Test-only-long-password-481!')
        self.client.force_login(self.admin)
        self.branch = Location.objects.create(company=self.company, code='branch', name='Branch', kind='branch')
    def rows(self, kind):
        return [{**dict(zip(HEADERS[kind], row)), '_row': number} for number, row in enumerate(EXAMPLES[kind], 2)]


class CatalogTests(Workspace):
    def test_preview_is_rolled_back_and_confirm_creates_only_catalog(self):
        result = apply_import(self.company, 'categories', self.rows('categories'), preview=True)
        self.assertEqual(result['created'], 2); self.assertEqual(Category.objects.count(), 0)
        apply_import(self.company, 'categories', self.rows('categories'))
        result = apply_import(self.company, 'products', self.rows('products'), preview=True)
        self.assertEqual(Product.objects.count(), 0)
        apply_import(self.company, 'products', self.rows('products'))
        product = Product.objects.get(unit='liter')
        self.assertEqual(product.price_minor, 450)
        self.assertIsNone(product.home_location_id)
        self.assertFalse(StockItem.objects.exists()); self.assertFalse(StockMovement.objects.exists())
        tequila = Product.objects.get(name='OLMECA Tequila')
        self.assertEqual(tequila.subcategory.parent, tequila.category)

    def test_invalid_later_row_rolls_back_every_row_and_existing_price(self):
        apply_import(self.company, 'categories', self.rows('categories'))
        rows = self.rows('products')
        apply_import(self.company, 'products', rows)
        before = Product.objects.get(barcode=rows[0]['barcode']).current_price_id
        rows[0]['price'], rows[1]['price'] = '22.00', 'NaN'
        with self.assertRaises(ValidationError): apply_import(self.company, 'products', rows)
        item = Product.objects.get(barcode=rows[0]['barcode'])
        self.assertEqual(item.current_price_id, before); self.assertEqual(item.prices.count(), 1)

    def test_duplicate_barcodes_and_unit_changes_are_rejected(self):
        apply_import(self.company, 'categories', self.rows('categories'))
        rows = self.rows('products')
        with self.assertRaises(ValidationError): apply_import(self.company, 'products', [rows[0], rows[0]])
        self.assertFalse(Product.objects.exists())
        apply_import(self.company, 'products', rows)
        rows[0]['unit'] = 'liter'
        with self.assertRaises(ValidationError): apply_import(self.company, 'products', rows)
        self.assertEqual(Product.objects.get(barcode=rows[0]['barcode']).unit, 'piece')

    def test_category_cycles_depth_and_wrong_product_subcategory(self):
        root = Category.objects.create(company=self.company, name='Drinks')
        child = Category.objects.create(company=self.company, name='Alcohol', parent=root)
        with self.assertRaises(ValidationError): Category.objects.create(company=self.company, name='Too deep', parent=child)
        root.parent = child
        with self.assertRaises(ValidationError): root.save()
        with self.assertRaises(ValidationError): Product.objects.create(company=self.company, name='Wrong', barcode='x', subcategory=child, price_minor=1)

    def test_downloadable_examples_roundtrip_in_all_formats(self):
        for kind in ('categories', 'products'):
            for extension in ('csv','xlsx','xml'):
                with self.subTest(kind=kind, extension=extension):
                    response = self.client.get(f'/catalog/{kind}/example.{extension}')
                    self.assertEqual(response.status_code, 200)
                    rows = parse_upload(SimpleUploadedFile(f'example.{extension}', response.content), kind)
                    self.assertEqual(len(rows), 2)
                    self.assertEqual(rows[0]['name'], EXAMPLES[kind][0][HEADERS[kind].index('name')])

    def test_upload_rejects_xml_entities_formulas_bad_columns_and_oversize(self):
        for name, data in [('bad.xml', b'<!DOCTYPE categories [<!ENTITY x "danger">]><categories><category><name>&x;</name></category></categories>'),
                           ('bad.csv', b'name,quantity\nMilk,100\n')]:
            with self.subTest(name=name), self.assertRaises(ValidationError): parse_upload(SimpleUploadedFile(name, data), 'categories')
        upload = SimpleUploadedFile('large.csv', b'x'); upload.size = 11 * 1024 * 1024
        with self.assertRaises(ValidationError): parse_upload(upload, 'products')

    def test_web_preview_confirm_and_replay_are_safe(self):
        example = self.client.get('/catalog/categories/example.csv').content
        response = self.client.post('/catalog/categories/import/', {'file': SimpleUploadedFile('example.csv', example)})
        self.assertEqual(response.status_code, 200); self.assertFalse(Category.objects.exists())
        token = response.context['token']
        self.assertEqual(self.client.post('/catalog/categories/import/', {'confirm':token}).status_code, 302)
        self.assertEqual(Category.objects.count(), 2)
        self.assertContains(self.client.post('/catalog/categories/import/', {'confirm':token}), 'preview has expired')

    def test_product_form_and_integration_screens(self):
        response = self.client.get('/manage/products/add/')
        self.assertNotContains(response, 'Opening quantity'); self.assertNotContains(response, 'Initial branch')
        self.assertContains(response, 'Liter'); self.assertContains(response, 'Sub-category')
        for url in ['/integrations/', '/integrations/rs/settings/', '/integrations/ad/settings/', '/integrations/waybills/']:
            with self.subTest(url=url): self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.get('/manage/stock/add/').status_code, 302)


class ReceivingTests(Workspace):
    def setUp(self):
        super().setUp()
        self.config = RSIntegration.objects.create(company=self.company, enabled=True, buyer_tin='123456789', service_user='fixture', password_encrypted=encrypt('fixture-password'))
        self.product = Product.objects.create(company=self.company, name='Juice', barcode='000042', unit='liter', price_minor=450)
        self.source = '<WAYBILL><ID>42</ID><WAYBILL_NUMBER>WB-42</WAYBILL_NUMBER><BUYER_TIN>123456789</BUYER_TIN><STATUS>2</STATUS><UNKNOWN>preserve</UNKNOWN><GOODS_LIST><GOODS><ID>10</ID><W_NAME>Juice</W_NAME><BAR_CODE>000042</BAR_CODE><UNIT_ID>3</UNIT_ID><QUANTITY>12.5</QUANTITY><PRICE>2</PRICE><AMOUNT>25</AMOUNT></GOODS></GOODS_LIST></WAYBILL>'
    def response(self, method, values=None):
        return ElementTree.fromstring(self.source if method == 'get_waybill' else '<WAYBILL_UNITS><WAYBILL_UNIT><ID>3</ID><NAME>ლიტრი</NAME></WAYBILL_UNIT></WAYBILL_UNITS>')
    def staged(self):
        with patch.object(RSClient, 'call', side_effect=self.response): return stage(self.config, '42')
    def test_receiving_assigns_location_once_and_preserves_source_and_price(self):
        item = self.staged()
        self.assertIn('<UNKNOWN>preserve</UNKNOWN>', item.source_xml)
        self.assertEqual(item.source_data['goods'][0]['DISPLAY_UNIT'], 'ლიტრი')
        self.assertFalse(StockItem.objects.exists())
        mappings = [{'product':self.product.pk, 'quantity':'12.5', 'reason':''}]
        receive(item, self.branch, mappings, self.admin, item.source_hash)
        self.assertEqual(StockItem.objects.get().quantity_milli, 12500)
        movement = StockMovement.objects.get(); self.assertEqual(movement.actor, self.admin); self.assertEqual(movement.reason, 'rs_waybill')
        with self.assertRaises(ValidationError): receive(item, self.branch, mappings, self.admin, item.source_hash)
        self.assertEqual(StockItem.objects.get().quantity_milli, 12500)
        self.product.refresh_from_db(); self.assertEqual(self.product.price_minor, 450)
        self.assertContains(self.client.get(f'/integrations/waybills/{item.pk}/'), 'Received into Branch')

    def test_liter_catalog_is_available_to_new_cashiers_without_breaking_older_clients(self):
        register = Register.objects.create(location=self.branch,name='POS',code='pos')
        StockItem.objects.create(product=self.product,location=self.branch)
        api = APIClient(); api.credentials(HTTP_AUTHORIZATION='Bearer '+register.issue_token())
        self.assertEqual(api.get('/api/v1/catalog/').json()['products'], [])
        catalog = api.get('/api/v1/catalog/?units=piece,kg,liter').json()
        self.assertEqual(catalog['products'][0]['unit'], 'liter')

    def test_web_receiving_requires_review_and_rechecks_the_source(self):
        item = self.staged(); url = f'/integrations/waybills/{item.pk}/'
        self.assertContains(self.client.get(url), 'Source quantity 12.5')
        data = {'source_hash':item.source_hash, 'location':str(self.branch.pk), 'units_confirmed':'on', 'line0-product':str(self.product.pk), 'line0-quantity':'12.5', 'line0-reason':''}
        self.source = self.source.replace('<QUANTITY>12.5', '<QUANTITY>13.5')
        with patch.object(RSClient, 'call', side_effect=self.response):
            response = self.client.post(url, data)
        self.assertContains(response, 'waybill changed in RS.ge')
        self.assertFalse(StockItem.objects.exists())

    def test_wrong_buyer_cancelled_or_duplicate_lines_are_rejected(self):
        original = self.source
        for source in [original.replace('123456789','987654321'), original.replace('<STATUS>2','<STATUS>-1'), original.replace('</GOODS_LIST>','<GOODS><ID>10</ID></GOODS></GOODS_LIST>')]:
            self.source = source
            with self.subTest(source=source), self.assertRaises(ValidationError): self.staged()
        self.assertFalse(ReceivedWaybill.objects.exists())

    def test_quantity_difference_requires_reason_and_failed_receipt_is_atomic(self):
        item = self.staged()
        for quantity in ['NaN','-1','0','1.0001','12']:
            with self.subTest(quantity=quantity), self.assertRaises(ValidationError):
                receive(item, self.branch, [{'product':self.product.pk,'quantity':quantity,'reason':''}], self.admin, item.source_hash)
        self.assertFalse(StockItem.objects.exists())
        receive(item,self.branch,[{'product':self.product.pk,'quantity':'12','reason':'Damaged bottle'}],self.admin,item.source_hash)
        self.assertEqual(StockItem.objects.get().quantity_milli,12000)

    def test_modified_received_document_is_not_reimported(self):
        item = self.staged()
        receive(item,self.branch,[{'product':self.product.pk,'quantity':'12.5'}],self.admin,item.source_hash)
        self.source = self.source.replace('<QUANTITY>12.5','<QUANTITY>13.5')
        with self.assertRaises(ValidationError): self.staged()
        self.assertEqual(StockItem.objects.get().quantity_milli,12500)

    def test_soap_authentication_requires_true_and_xml_is_bounded(self):
        def response(value):
            return f'<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body><chek_service_userResponse xmlns="http://tempuri.org/"><chek_service_userResult>{value}</chek_service_userResult></chek_service_userResponse></s:Body></s:Envelope>'.encode()
        opener = Mock(); opener.open.return_value.__enter__ = Mock(return_value=Mock(read=Mock(return_value=response('false')))); opener.open.return_value.__exit__ = Mock(return_value=False)
        with patch('commerce.rs_ge.urllib.request.build_opener', return_value=opener), self.assertRaises(ValidationError): RSClient(self.config).call('chek_service_user')
        with self.assertRaises(ValidationError): parse_xml(b'<!DOCTYPE x [<!ENTITY y SYSTEM "file:///etc/passwd">]><x>&y;</x>')
        with self.assertRaises(ValidationError): parse_xml(('<x>' * 35 + '</x>' * 35).encode())


class DirectoryAndDeviceTests(Workspace):
    def setUp(self):
        super().setUp()
        self.config = DirectoryIntegration.objects.create(company=self.company,enabled=True,host='dc.example.test',base_dn='DC=example,DC=test',bind_user='service@example.test',password_encrypted=encrypt('fixture-password'))
        self.guid=uuid4()
        self.person={'guid':str(self.guid),'username':'cashier@example.test','name':'Test','surname':'Cashier','email':'','dn':'CN=Cashier,DC=example,DC=test'}
    def test_password_encryption_and_ad_login_uses_guid_and_bind(self):
        self.assertNotIn('fixture-password',self.config.password_encrypted)
        self.assertEqual(decrypt(self.config.password_encrypted),'fixture-password')
        user=get_user_model().objects.create_user('cashier@example.test');user.set_unusable_password();user.save()
        DirectoryIdentity.objects.create(user=user,integration=self.config,object_guid=self.guid)
        with patch('commerce.directory.lookup',return_value=self.person) as lookup_mock, patch('commerce.directory.connect') as connection:
            self.assertEqual(authenticate(username=user.username,password='AD fixture password'),user)
            lookup_mock.assert_called_once_with(self.config,guid=self.guid)
            connection.assert_called_once_with(self.config,self.person['dn'],'AD fixture password')
        self.config.enabled=False;self.config.save()
        with patch('commerce.directory.connect') as connection:
            self.assertIsNone(authenticate(username=user.username,password='anything')); connection.assert_not_called()

    def test_ad_provisioning_and_permissions_do_not_enable_local_password(self):
        with patch('backoffice.integrations.lookup',return_value=self.person):
            response=self.client.post('/integrations/directory/users/',{'username':'cashier'})
            selected=response.context['selection']
            response=self.client.post('/integrations/directory/users/',{'selection':selected})
        user=get_user_model().objects.get(username=self.person['username'])
        self.assertEqual(response.status_code,302);self.assertFalse(user.has_usable_password())
        self.assertFalse(user.pos_access.branches.exists());self.assertFalse(user.pos_access.permissions.exists())
        self.assertNotContains(self.client.get(f'/team/{user.pk}/'),'name="password"')
        self.assertFalse(user.is_staff)

    def test_directory_search_escapes_input_and_rejects_disabled_account(self):
        values={'objectGUID':[str(self.guid)],'userPrincipalName':[self.person['username']],'userAccountControl':[514]}
        connection=Mock(entries=[SimpleNamespace(entry_attributes_as_dict=values,entry_dn=self.person['dn'])],result={'result':0})
        with patch('commerce.directory.connect',return_value=connection),self.assertRaises(ValidationError): lookup(self.config,username='*)(objectClass=*)')
        self.assertIn('\\2a\\29\\28objectClass=\\2a\\29',connection.search.call_args.args[1])
        connection.unbind.assert_called_once()

    def test_configuration_and_inventory_are_permission_gated(self):
        user=get_user_model().objects.create_user('employee','long-example-password-723!')
        access=EmployeeAccess.objects.create(user=user,company=self.company,application='backend',all_branches=True)
        self.client.force_login(user)
        for url in ['/integrations/','/integrations/rs/settings/','/catalog/products/import/','/integrations/waybills/']:
            self.assertEqual(self.client.get(url).status_code,403)
        access.permissions.add(AccessPermission.objects.get(code='manage_inventory'))
        self.assertEqual(self.client.get('/integrations/').status_code,200)
        self.assertEqual(self.client.get('/integrations/rs/settings/').status_code,403)

    def test_system_information_report_is_bounded_and_visible(self):
        register=Register.objects.create(location=self.branch,name='POS',code='pos')
        api=APIClient();api.credentials(HTTP_AUTHORIZATION='Bearer '+register.issue_token())
        info={'os':'Windows','version':'Windows 11','arch':'x64','cpu':'Example CPU','cores':8,'ram_bytes':16*1024**3,
              'disks':[{'name':'C:','total_bytes':256*1024**3,'free_bytes':100*1024**3}]}
        data={'version':'0.5.0','platform':'win-x64','updater_ready':True,'system_info':info}
        self.assertEqual(api.post('/api/v1/cashier/updates/',data,format='json').status_code,200)
        register.refresh_from_db();self.assertEqual(register.system_info,info)
        self.assertContains(self.client.get(f'/manage/registers/{register.pk}/'),'Example CPU')
        info['cores']=100000
        self.assertEqual(api.post('/api/v1/cashier/updates/',data,format='json').status_code,400)
        register.refresh_from_db();self.assertEqual(register.system_info['cores'],8)
