from decimal import Decimal
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from commerce.models import Company, Location, Product, Category, StockItem, StockAdjustment, EmployeeAccess, AccessGroup, AccessPermission, Register

class SetupForm(forms.Form):
    name = forms.CharField(label='Company name (ENG)', max_length=150)
    name_ka = forms.CharField(label='Company name (GEO)', max_length=150)
    address = forms.CharField(label='Company address', max_length=300, required=False)
    phone = forms.CharField(label='Company phone number', max_length=40, required=False)
    first_name = forms.CharField(label='Admin first name', max_length=255, required=False)
    last_name = forms.CharField(label='Admin last name', max_length=255, required=False)
    email = forms.EmailField(label='Admin email')
    username = forms.CharField(label='Admin username', max_length=150)
    password = forms.CharField(label='Admin password', widget=forms.PasswordInput, max_length=1024)
    password_confirm = forms.CharField(label='Confirm password', widget=forms.PasswordInput, max_length=1024)
    def clean(self):
        data = super().clean()
        if data.get('password') != data.get('password_confirm'): self.add_error('password_confirm','Passwords do not match.')
        if get_user_model().objects.filter(username=data.get('username')).exists(): self.add_error('username','This username already exists.')
        if data.get('password'):
            try: validate_password(data['password'], get_user_model()(username=data.get('username',''),email=data.get('email','')))
            except ValidationError as error: self.add_error('password',error)
        return data

class CompanyForm(forms.ModelForm):
    name_ka = forms.CharField(label='Company name (GEO)', max_length=150)
    class Meta:
        model = Company
        fields = ['name','name_ka','address','phone','theme','advertisement','removal_notice_minutes']
        labels = {'name':'Company name (ENG)','advertisement':'Customer display welcome text'}

class ScopedForm(forms.ModelForm):
    def __init__(self,*args,company,**kwargs):
        super().__init__(*args,**kwargs)
        self.company = company
        if hasattr(self.instance,'company_id'): self.instance.company = company

class LocationForm(ScopedForm):
    class Meta:
        model = Location
        fields = ['name','code','address','active']

class CategoryForm(ScopedForm):
    class Meta:
        model = Category
        fields = ['name','name_ka']

class ProductForm(ScopedForm):
    price = forms.DecimalField(label='Selling price (GEL)',max_digits=9,decimal_places=2,min_value=0,max_value=1000000)
    opening_quantity = forms.DecimalField(label='Opening quantity',max_digits=10,decimal_places=3,min_value=0,max_value=1000000,required=False,initial=0)
    class Meta:
        model = Product
        fields = ['name','name_ka','barcode','category','home_location','unit','price','opening_quantity','active']
        labels = {'home_location':'Initial branch or warehouse','name_ka':'Product name (GEO)'}
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['home_location'].queryset = Location.objects.filter(company=self.company,active=True).order_by('name')
        self.fields['category'].queryset = Category.objects.filter(company=self.company).order_by('name')
        if not self.instance._state.adding:
            self.fields.pop('opening_quantity')
            self.fields['unit'].disabled = True
            self.fields['price'].initial = Decimal(self.instance.price_minor)/100
            self.fields['home_location'].queryset = Location.objects.filter(company=self.company).order_by('name')
    def clean(self):
        data = super().clean()
        if data.get('price') is not None: self.instance.price_minor = int(data['price']*100)
        quantity = data.get('opening_quantity') or Decimal(0)
        if data.get('unit')=='piece' and quantity!=quantity.to_integral_value(): self.add_error('opening_quantity','Piece quantities must be whole numbers.')
        return data
    @transaction.atomic
    def save_for(self,actor):
        new = self.instance._state.adding
        item = super().save()
        quantity = self.cleaned_data.get('opening_quantity') or Decimal(0)
        if new and quantity:
            StockAdjustment.objects.create(stock_item=StockItem.objects.get(product=item,location=item.home_location),quantity_milli=int(quantity*1000),reason='Opening stock',actor=actor)
        return item

class AssignmentForm(ScopedForm):
    class Meta:
        model = StockItem
        fields = ['product','location','enabled']
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['product'].queryset = Product.objects.filter(company=self.company,active=True).order_by('name')
        self.fields['location'].queryset = Location.objects.filter(company=self.company,active=True).order_by('name')
        if not self.instance._state.adding:
            for field in ['product','location']: self.fields[field].disabled=True

class AdjustmentForm(forms.Form):
    quantity = forms.DecimalField(label='Quantity to add or remove',max_digits=10,decimal_places=3,min_value=-1000000,max_value=1000000,help_text='Use a negative number to remove stock. Existing movements stay in history.')
    reason = forms.CharField(max_length=250,min_length=3)
    def __init__(self,*args,stock,**kwargs):
        super().__init__(*args,**kwargs)
        self.stock=stock
    def clean_quantity(self):
        value=self.cleaned_data['quantity']
        if not value: raise forms.ValidationError('Enter a nonzero quantity.')
        if self.stock.product.unit=='piece' and value!=value.to_integral_value(): raise forms.ValidationError('Piece quantities must be whole numbers.')
        return value

class RegisterForm(forms.ModelForm):
    class Meta:
        model=Register
        fields=['location','name','code','active']
        labels={'location':'Branch'}
    def __init__(self,*args,company,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['location'].queryset=Location.objects.filter(company=company,kind='branch',active=True).order_by('name')
        if not self.instance._state.adding:
            self.fields['location'].queryset=Location.objects.filter(company=company,kind='branch').order_by('name')
            self.fields['location'].disabled=True
            self.fields['code'].disabled=True

class GroupForm(ScopedForm):
    class Meta:
        model=AccessGroup
        fields=['name','permissions']
        widgets={'permissions':forms.CheckboxSelectMultiple}

class EmployeeForm(forms.Form):
    username=forms.CharField(max_length=150)
    email=forms.EmailField(required=False)
    name=forms.CharField(label='First name',max_length=255,required=False)
    surname=forms.CharField(label='Last name',max_length=255,required=False)
    password=forms.CharField(widget=forms.PasswordInput,max_length=1024,required=False,help_text='Leave empty to keep the current password when editing.')
    password_confirm=forms.CharField(label='Confirm password',widget=forms.PasswordInput,max_length=1024,required=False)
    application=forms.ChoiceField(choices=EmployeeAccess._meta.get_field('application').choices)
    all_branches=forms.BooleanField(label='Allow all branches',required=False)
    branches=forms.ModelMultipleChoiceField(queryset=Location.objects.none(),required=False,widget=forms.CheckboxSelectMultiple)
    groups=forms.ModelMultipleChoiceField(queryset=AccessGroup.objects.none(),required=False,widget=forms.CheckboxSelectMultiple)
    permissions=forms.ModelMultipleChoiceField(queryset=AccessPermission.objects.all(),required=False,widget=forms.CheckboxSelectMultiple)
    is_active=forms.BooleanField(label='Active',required=False,initial=True)
    def __init__(self,*args,company,user=None,actor=None,**kwargs):
        self.company,self.user,self.actor=company,user,actor
        initial=kwargs.setdefault('initial',{})
        if user:
            initial.update({field:getattr(user,field) for field in ['username','email','name','surname','is_active']})
            access=EmployeeAccess.objects.filter(user=user).first()
            if access: initial.update(application=access.application,all_branches=access.all_branches,branches=access.branches.all(),groups=access.groups.all(),permissions=access.permissions.all())
        super().__init__(*args,**kwargs)
        self.fields['branches'].queryset=Location.objects.filter(company=company,kind='branch',active=True).order_by('name')
        self.fields['groups'].queryset=AccessGroup.objects.filter(company=company).order_by('name')
    def clean(self):
        data=super().clean()
        if not self.user and not data.get('password'): self.add_error('password','Enter a password for the new user.')
        if data.get('password')!=data.get('password_confirm'): self.add_error('password_confirm','Passwords do not match.')
        if get_user_model().objects.filter(username=data.get('username')).exclude(pk=self.user.pk if self.user else None).exists(): self.add_error('username','This username already exists.')
        if data.get('password'):
            try: validate_password(data['password'],get_user_model()(username=data.get('username',''),email=data.get('email','')))
            except ValidationError as error: self.add_error('password',error)
        if self.user and self.user.pk==self.actor.pk and (not data.get('is_active') or data.get('application')=='cashier'): raise forms.ValidationError('You cannot remove your own BackOffice access.')
        if self.user and self.user.is_superuser and (not data.get('is_active') or data.get('application')=='cashier'): raise forms.ValidationError('The installation administrator must retain active BackOffice access.')
        return data
    @transaction.atomic
    def save(self):
        data=self.cleaned_data
        user=self.user or get_user_model()()
        for field in ['username','email','name','surname','is_active']: setattr(user,field,data[field])
        user.is_staff=data['application'] in {'backend','both'}
        if data.get('password'): user.set_password(data['password'])
        user.save()
        access,_=EmployeeAccess.objects.update_or_create(user=user,defaults={'company':self.company,'application':data['application'],'all_branches':data['all_branches']})
        for field in ['branches','groups','permissions']: getattr(access,field).set(data[field])
        return user
