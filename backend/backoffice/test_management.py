import base64, hashlib, io, json, subprocess, tempfile, uuid
from pathlib import Path
from datetime import timedelta
from PIL import Image
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from commerce.models import Company, Installation, Location, Register, PairingCode, DeviceEnrollment, Advertisement, CashierRelease, UpdateRollout, UpdateDelivery, LiveBasket, BasketCommand, EmployeeAccess
from commerce.enrollment import generate_code
from commerce.updates import import_release

class ManagementTests(TestCase):
    def setUp(self):
        self.company=Company.objects.create(name='Test Stores',name_ka='ტესტი',code='test')
        Installation.objects.update_or_create(pk=1,defaults={'completed_at':timezone.now()})
        self.owner=get_user_model().objects.create_superuser('owner','Test-only-long-secret-523!')
        self.branch=Location.objects.create(company=self.company,name='Vake',code='vake',kind='branch')
        self.other=Location.objects.create(company=self.company,name='Saburtalo',code='sab',kind='branch')
        self.register=Register.objects.create(location=self.branch,name='Till 1',code='till1')
        self.second=Register.objects.create(location=self.other,name='Till 2',code='till2')
        self.api=APIClient();self.api.credentials(HTTP_AUTHORIZATION='Bearer '+self.register.issue_token());self.client.force_login(self.owner)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        override=override_settings(MEDIA_ROOT=Path(self.tmp.name)/'media',SIMPLEPOS_RELEASE_DIR=Path(self.tmp.name)/'releases',SIMPLEPOS_RELEASE_PUBLIC_KEY=Path(self.tmp.name)/'public.pem')
        override.enable();self.addCleanup(override.disable)

    def test_branch_selection_filters_history_and_notice_setting_validates(self):
        LiveBasket.objects.create(register=self.register,basket_id=uuid.uuid4(),state='active',lines_json=json.dumps([{'name':'Milk','quantity_milli':1000,'total_minor':450,'key':'x'}]))
        for register,product in [(self.register,'Milk'),(self.second,'Hidden product')]:
            BasketCommand.objects.create(register=register,basket_id=uuid.uuid4(),expected_revision=1,line_key='x',product_name=product,reason='Duplicate scan',requested_by=self.owner,status='applied',expires_at=timezone.now(),quantity_milli=1000)
        self.assertNotContains(self.client.get('/checkouts/'),'Duplicate scan')
        response=self.client.get('/checkouts/',{'branch':self.branch.pk});self.assertContains(response,'Confirmed by POS');self.assertNotContains(response,'Hidden product')
        self.assertEqual(self.client.get('/checkouts/',{'branch':'invalid'}).status_code,404)
        self.company.removal_notice_minutes=3;self.company.save()
        self.assertEqual(self.api.get('/api/v1/catalog/').json()['company']['removal_notice_minutes'],3)
        invalid=self.client.post('/company/',{'name':'Test','name_ka':'ტესტი','theme':'mint','removal_notice_minutes':'0'})
        self.assertIn('removal_notice_minutes',invalid.context['form'].errors)

    def test_pos_creation_reserves_terminal_and_code_is_single_use(self):
        response=self.client.post('/manage/registers/add/',{'location':str(self.branch.pk),'name':'Front counter','code':'front','active':'on'})
        self.assertEqual(response.status_code,200);register=Register.objects.get(code='front');code=response.context['code']
        other=Register.objects.create(location=self.branch,name='Other till',code='other');generate_code(self.branch,self.owner,other)
        self.assertGreater(PairingCode.objects.get(register=register).expires_at,timezone.now())
        api=APIClient();identity={'installation_id':str(uuid.uuid4()),'installation_secret':'test-only-secret-'*4,'action':'pair','code':code}
        self.assertEqual(api.post('/api/v1/cashier/enrollment/',identity,format='json').status_code,200)
        self.assertEqual(DeviceEnrollment.objects.get().register,register)
        identity['installation_id']=str(uuid.uuid4());self.assertEqual(api.post('/api/v1/cashier/enrollment/',identity,format='json').status_code,403)
        self.client.post(f'/registers/{register.pk}/pair/');self.assertEqual(PairingCode.objects.filter(register=register).count(),1)

    def test_ad_upload_is_scoped_scheduled_and_paused(self):
        image=io.BytesIO();Image.new('RGB',(100,80),'green').save(image,format='PNG')
        response=self.client.post('/advertisements/add/',{'title':'Spring','text':'Save today','upload':SimpleUploadedFile('ad.png',image.getvalue(),'image/png'),'active':'on','branches':[str(self.branch.pk)],'duration_seconds':'15','position':'1'})
        self.assertEqual(response.status_code,302);ad=Advertisement.objects.get();self.assertTrue(ad.image.name.endswith('.webp'))
        catalog=self.api.get('/api/v1/catalog/').json();self.assertEqual(len(catalog['advertisements']),1)
        url=catalog['advertisements'][0]['image']['url'];self.assertEqual(self.api.get(url).status_code,200)
        other=APIClient();other.credentials(HTTP_AUTHORIZATION='Bearer '+self.second.issue_token())
        self.assertEqual(other.get('/api/v1/catalog/').json()['advertisements'],[]);self.assertEqual(other.get(url).status_code,404)
        ad.ends_at=timezone.now()-timedelta(seconds=1);ad.save();self.assertEqual(self.api.get('/api/v1/catalog/').json()['advertisements'],[])
        ad.ends_at=None;ad.active=False;ad.save();self.assertEqual(self.api.get(url).status_code,404)
        self.assertEqual(APIClient().get(url).status_code,401)
        for url in ['/advertisements/','/advertisements/add/',f'/advertisements/{ad.pk}/','/updates/','/updates/import/']:
            self.assertEqual(self.client.get(url).status_code,200,url)

    def poll(self,**kw):
        return self.api.post('/api/v1/cashier/updates/',{'version':'0.4.0','platform':'win-x64','updater_ready':True,**kw},format='json')

    def test_rollout_targets_schedule_status_and_cancellation(self):
        release=CashierRelease.objects.create(version='0.5.0',platform='win-x64',filename='Cashier.zip',size=1,sha256='a'*64,uploaded_by=self.owner)
        self.assertEqual(self.client.post('/updates/',{'release':str(release.pk),'branches':[str(self.branch.pk)]}).status_code,302)
        rollout=UpdateRollout.objects.get();delivery=rollout.deliveries.get();self.assertEqual(delivery.register,self.register)
        self.assertEqual(self.client.get(f'/updates/{rollout.pk}/').status_code,200)
        target=self.poll().json()['update'];self.assertEqual(target['version'],'0.5.0')
        self.poll(delivery_id=target['id'],status='waiting',detail='Checkout has a basket');delivery.refresh_from_db();self.assertEqual(delivery.detail,'Checkout has a basket')
        other=APIClient();other.credentials(HTTP_AUTHORIZATION='Bearer '+self.second.issue_token())
        self.assertIsNone(other.post('/api/v1/cashier/updates/',{'version':'0.4.0','platform':'win-x64','updater_ready':True,'delivery_id':target['id'],'status':'installed'},format='json').json()['update'])
        self.poll(version='0.5.0');delivery.refresh_from_db();self.assertEqual(delivery.status,'installed')
        self.client.post('/updates/',{'release':str(release.pk),'all_branches':'on'});latest=UpdateRollout.objects.latest('created_at');self.assertEqual(latest.deliveries.count(),2)
        self.client.post(f'/updates/{latest.pk}/cancel/');self.assertIsNone(self.poll().json()['update'])
        latest.cancelled_at=None;latest.starts_at=timezone.now()+timedelta(hours=1);latest.save()
        self.assertNotEqual(self.poll().json()['update']['id'],str(latest.deliveries.get(register=self.register).pk))
        self.assertEqual(self.api.post('/api/v1/cashier/updates/',[],format='json').status_code,400)

    def test_signed_import_rejects_corruption_and_replacement(self):
        root=Path(self.tmp.name);private=root/'private.pem';public=root/'public.pem'
        subprocess.run(['openssl','genpkey','-algorithm','RSA','-pkeyopt','rsa_keygen_bits:3072','-out',str(private)],check=True,capture_output=True)
        subprocess.run(['openssl','pkey','-in',str(private),'-pubout','-out',str(public)],check=True,capture_output=True)
        artifact=b'Test-only signed fixture';raw=json.dumps({'schema':1,'version':'0.5.0','platform':'win-x64','filename':'Cashier.zip','size':len(artifact),'sha256':hashlib.sha256(artifact).hexdigest()}).encode()
        (root/'manifest.json').write_bytes(raw)
        signature=subprocess.run(['openssl','dgst','-sha256','-sign',str(private),str(root/'manifest.json')],check=True,capture_output=True).stdout
        def upload(content=artifact,manifest=raw):
            return import_release(SimpleUploadedFile('manifest.json',manifest),SimpleUploadedFile('manifest.sig',base64.b64encode(signature)),SimpleUploadedFile('Cashier.zip',content),self.owner)
        with self.assertRaises(ValidationError):upload(artifact[:-1]+b'x')
        with self.assertRaises(ValidationError):upload(manifest=raw+b' ')
        upload();self.assertEqual(self.client.get('/cashier/releases/win-x64/versions/0.5.0/manifest.json').status_code,200)
        with self.assertRaises(ValidationError):upload()
        self.assertEqual(CashierRelease.objects.count(),1)
        self.assertEqual(self.client.get('/cashier/releases/win-x64/versions/0.5.0/private.pem').status_code,404)

    def test_permission_gates(self):
        user=get_user_model().objects.create_user('cashier','test-password');EmployeeAccess.objects.create(user=user,company=self.company,application='both');self.client.force_login(user)
        for url in ['/advertisements/','/updates/','/updates/import/','/advertisements/add/']:self.assertEqual(self.client.get(url).status_code,403)
