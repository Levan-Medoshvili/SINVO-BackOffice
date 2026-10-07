import re
from datetime import timedelta
from decimal import Decimal
from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction, IntegrityError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.debug import sensitive_post_parameters
from commerce.models import (RSIntegration, DirectoryIntegration, DirectoryIdentity, ReceivedWaybill,
    EmployeeAccess, Product, Location, Installation)
from commerce.integration_secrets import encrypt
from commerce.directory import lookup
from commerce.rs_ge import RSClient, stage, receive
from .access import backoffice, allowed, branches_for


class SecretForm(forms.ModelForm):
    password = forms.CharField(required=False, max_length=1024, widget=forms.PasswordInput,
        help_text='Leave empty to keep the saved password.')
    def clean(self):
        data = super().clean()
        if data.get('enabled') and not (data.get('password') or self.instance.password_encrypted):
            self.add_error('password', 'Enter the service account password.')
        return data
    def save(self, commit=True):
        item = super().save(commit=False)
        if self.cleaned_data.get('password'): item.password_encrypted = encrypt(self.cleaned_data['password'])
        item.checked_at = None
        if commit: item.save()
        return item


class RSForm(SecretForm):
    class Meta:
        model = RSIntegration
        fields = ['enabled', 'buyer_tin', 'service_user', 'password']
        labels = {'buyer_tin': 'Company identification number (TIN)', 'service_user': 'RS.ge service user'}
    def clean_buyer_tin(self):
        value = self.cleaned_data['buyer_tin'].strip()
        if not re.fullmatch(r'[0-9]{9,11}', value): raise ValidationError('Enter the company TIN, 9–11 digits.')
        if not self.instance._state.adding and value != RSIntegration.objects.get(pk=self.instance.pk).buyer_tin and ReceivedWaybill.objects.filter(company_id=self.instance.pk).exists():
            raise ValidationError('This installation has waybills for the saved company TIN. It cannot be changed.')
        return value


class ADForm(SecretForm):
    class Meta:
        model = DirectoryIntegration
        fields = ['enabled', 'host', 'port', 'base_dn', 'bind_user', 'password', 'ca_certificate']
        labels = {'host': 'Domain controller hostname', 'bind_user': 'Directory service account (UPN)',
                  'ca_certificate': 'Private CA certificate (optional)'}
        help_texts = {'host': 'LDAPS is required. Use the hostname on the server certificate.', 'base_dn': 'For example: DC=company,DC=local',
                      'ca_certificate': 'PEM certificate for your private certificate authority. Leave empty to use system trust.'}
        widgets = {'ca_certificate': forms.Textarea(attrs={'rows': 4, 'maxlength': 20000})}
    def clean_host(self):
        host = self.cleaned_data['host'].strip()
        if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?', host): raise ValidationError('Enter a hostname only, without a scheme, path or port.')
        return host
    def clean_ca_certificate(self):
        value = self.cleaned_data['ca_certificate'].strip()
        if value:
            from cryptography.x509 import load_pem_x509_certificates
            try:
                if len(value) > 20000 or not load_pem_x509_certificates(value.encode()): raise ValueError()
            except ValueError: raise ValidationError('Enter a PEM certificate up to 20 KB.')
        return value


@backoffice()
def index(request):
    if not allowed(request.user, 'manage_integrations') and not allowed(request.user, 'manage_inventory'): raise PermissionDenied()
    return render(request, 'backoffice/integrations.html', {'nav': 'integrations',
        'rs': RSIntegration.objects.filter(company=request.company).first(),
        'ad': DirectoryIntegration.objects.filter(company=request.company).first() if allowed(request.user, 'manage_integrations') else None})


@backoffice('manage_integrations')
@sensitive_post_parameters('password')
def settings(request, kind):
    if kind not in {'rs', 'ad'}: raise PermissionDenied()
    model, form_class, title = (RSIntegration, RSForm, 'RS.ge') if kind == 'rs' else (DirectoryIntegration, ADForm, 'Active Directory')
    item = model.objects.filter(company=request.company).first() or model(company=request.company)
    form = form_class(request.POST or None, instance=item)
    if request.method == 'POST' and form.is_valid():
        item = form.save()
        messages.success(request, title + ' settings saved.')
        return redirect('backoffice:integration-settings', kind=kind)
    return render(request, 'backoffice/integration-settings.html', {'nav': 'integrations', 'form': form, 'kind': kind, 'title': title, 'item': item})


@backoffice('manage_integrations')
def test_connection(request, kind):
    if request.method != 'POST': raise PermissionDenied()
    try:
        if kind == 'rs':
            item = get_object_or_404(RSIntegration, company=request.company)
            RSClient(item).call('chek_service_user')
        elif kind == 'ad':
            from commerce.directory import connect
            from commerce.integration_secrets import decrypt
            item = get_object_or_404(DirectoryIntegration, company=request.company)
            if not item.enabled: raise ValidationError('Enable Active Directory first.')
            connection = connect(item, item.bind_user, decrypt(item.password_encrypted))
            try:
                connection.search(item.base_dn, '(objectClass=*)', search_scope='BASE', attributes=['distinguishedName'], size_limit=1, time_limit=5)
                if connection.result.get('result') != 0 or len(connection.entries) != 1: raise ValidationError('The base DN could not be read.')
            finally: connection.unbind()
        else: raise PermissionDenied()
        item.checked_at = timezone.now(); item.save(update_fields=['checked_at'])
        messages.success(request, 'Connection verified.')
    except ValidationError as error: messages.error(request, '; '.join(error.messages))
    except Exception:
        messages.error(request, 'Connection test failed. Check the server, base DN and account access.')
    return redirect('backoffice:integration-settings', kind=kind)


@backoffice('manage_users')
def directory_users(request):
    config = get_object_or_404(DirectoryIntegration, company=request.company)
    context = {'nav': 'integrations'}
    if request.method == 'POST':
        try:
            if request.POST.get('selection'):
                selected = signing.loads(request.POST['selection'], salt='ad-provision', max_age=600)
                if selected['company'] != str(request.company.pk): raise PermissionDenied()
                person = lookup(config, guid=selected['guid'])
                with transaction.atomic():
                    Installation.objects.select_for_update().get(pk=1)
                    if get_user_model().objects.filter(username__iexact=person['username']).exists() or DirectoryIdentity.objects.filter(integration=config, object_guid=person['guid']).exists():
                        raise ValidationError('This user already exists. Manage its permissions in Users. Existing local accounts are never linked automatically.')
                    user = get_user_model()(username=person['username'], name=person['name'], surname=person['surname'], email=person['email'], is_active=True)
                    user.set_unusable_password(); user.full_clean(); user.save()
                    DirectoryIdentity.objects.create(user=user, integration=config, object_guid=person['guid'])
                    EmployeeAccess.objects.create(user=user, company=request.company, application='cashier')
                messages.success(request, 'AD user added. Choose application access, branches and permissions, then save.')
                return redirect('backoffice:user-edit', identifier=user.pk)
            person = lookup(config, username=request.POST.get('username', '')[:150].strip())
            context.update(person=person, selection=signing.dumps({'company': str(request.company.pk), 'guid': person['guid']}, salt='ad-provision'))
        except (ValidationError, IntegrityError, signing.BadSignature) as error:
            messages.error(request, '; '.join(error.messages) if isinstance(error, ValidationError) else 'The selection expired or this user was already added. Search again.')
    return render(request, 'backoffice/directory-users.html', context)


class SearchForm(forms.Form):
    start = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    end = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    confirmation = forms.ChoiceField(choices=[('0', 'Unconfirmed'), ('1', 'Confirmed'), ('-1', 'Rejected')])
    def clean(self):
        data = super().clean()
        if data.get('start') and data.get('end') and not 0 <= (data['end'] - data['start']).days <= 31:
            raise ValidationError('Choose a period of at most 31 days, with the end on or after the start.')
        return data


def receiving_locations(request):
    # Warehouse inventory is company scoped, matching the existing inventory permission.
    return Location.objects.filter(company=request.company, active=True).filter(
        Q(kind='warehouse') | Q(pk__in=branches_for(request.user, request.company)))


@backoffice('manage_inventory')
def waybills(request):
    config = RSIntegration.objects.filter(company=request.company).first()
    form = SearchForm(request.POST if request.method == 'POST' and request.POST.get('action') == 'search' else None,
        initial={'start': timezone.localdate() - timedelta(days=7), 'end': timezone.localdate(), 'confirmation': '0'})
    context = {'nav': 'integrations', 'form': form, 'configured': bool(config and config.enabled),
               'receipts': ReceivedWaybill.objects.filter(company=request.company).order_by('-fetched_at')[:100]}
    if request.method == 'POST':
        try:
            if not config or not config.enabled: raise ValidationError('Configure and enable RS.ge first.')
            if request.POST.get('action') == 'fetch':
                item = stage(config, request.POST.get('identifier', ''))
                return redirect('backoffice:waybill', identifier=item.pk)
            if form.is_bound and form.is_valid():
                context['incoming'] = RSClient(config).incoming(form.cleaned_data['start'], form.cleaned_data['end'], int(form.cleaned_data['confirmation']))
                context['searched'] = True
        except ValidationError as error: messages.error(request, '; '.join(error.messages))
    return render(request, 'backoffice/waybills.html', context)


@backoffice('manage_inventory')
def waybill(request, identifier):
    item = get_object_or_404(ReceivedWaybill, company=request.company, pk=identifier)
    products = Product.objects.filter(company=request.company, active=True).order_by('name')
    locations = receiving_locations(request)
    lines = []
    for number, line in enumerate(item.source_data['goods']):
        initial_product = products.filter(barcode=line.get('BAR_CODE', '')).first()
        class LineForm(forms.Form):
            product = forms.ModelChoiceField(queryset=products)
            quantity = forms.DecimalField(max_digits=10, decimal_places=3, min_value=Decimal('0.001'), max_value=1000000)
            reason = forms.CharField(required=False, max_length=250, label='Difference / conversion reason')
        form = LineForm(request.POST or None, prefix=f'line{number}', initial={'product': initial_product, 'quantity': line.get('QUANTITY', '')})
        lines.append({'source': line, 'form': form})
    class ReceiptForm(forms.Form):
        location = forms.ModelChoiceField(queryset=locations, label='Receiving branch or warehouse')
        units_confirmed = forms.BooleanField(label='I checked the products, source units and received quantities, including any conversion.')
    form = ReceiptForm(request.POST or None)
    if request.method == 'POST' and not item.received_at:
        valid = form.is_valid()
        valid_lines = all([line['form'].is_valid() for line in lines])
        if valid and valid_lines:
            try:
                config = get_object_or_404(RSIntegration, company=request.company)
                latest = stage(config, item.external_id)
                if latest.source_hash != request.POST.get('source_hash'): raise ValidationError('The waybill changed in RS.ge. Reload this page and review the new values.')
                mappings = [{**line['form'].cleaned_data, 'product': line['form'].cleaned_data['product'].pk} for line in lines]
                receive(item, form.cleaned_data['location'], mappings, request.user, latest.source_hash)
                messages.success(request, 'Waybill received. Stock and audit history are updated.')
                return redirect('backoffice:waybill', identifier=item.pk)
            except (ValidationError, Product.DoesNotExist) as error:
                form.add_error(None, error if isinstance(error, ValidationError) else 'A product changed. Reload and review the receipt.')
    return render(request, 'backoffice/waybill.html', {'nav': 'integrations', 'item': item, 'lines': lines, 'form': form})
