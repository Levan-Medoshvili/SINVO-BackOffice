"""The company workspace. Mutations share commerce validation and audit services."""
import hmac
import json
import secrets
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout, update_session_auth_hash
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.db.models.deletion import ProtectedError
from django.db.models.functions import TruncDate
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_POST

from commerce.access import backend_allowed, count_login_attempt
from commerce.enrollment import client_address, generate_code, review_request
from commerce.models import (Company, Installation, Location, Category, Product, StockItem,
    StockAdjustment, Register, Sale, EmployeeAccess, AccessGroup, EnrollmentRequest, LiveBasket)
from commerce.supervision import scoped_baskets, request_removal
from .access import backoffice, allowed, branches_for
from .forms import (SetupForm, CompanyForm, LocationForm, CategoryForm, ProductForm,
    AssignmentForm, AdjustmentForm, GroupForm, EmployeeForm, RegisterForm)


class UnlockForm(forms.Form):
    setup_key = forms.CharField(label='Installation setup key', widget=forms.PasswordInput, max_length=200)


@never_cache
@sensitive_post_parameters('password', 'password_confirm', 'setup_key')
def setup(request):
    installation, _ = Installation.objects.get_or_create(pk=1)
    if installation.completed_at:
        return redirect('backoffice:login')
    if not request.session.get('setup_unlocked'):
        form = UnlockForm(request.POST or None)
        if request.method == 'POST' and form.is_valid():
            token = settings.SIMPLEPOS_SETUP_TOKEN
            permitted = count_login_attempt('setup:' + client_address(request), 10)
            if permitted and len(token) >= 24 and hmac.compare_digest(form.cleaned_data['setup_key'], token):
                request.session.cycle_key()
                request.session['setup_unlocked'] = True
                return redirect('backoffice:setup')
            form.add_error(None, 'The setup key is invalid or too many attempts were made. Contact your installation administrator.')
        return render(request, 'backoffice/unlock.html', {'form': form})
    form = SetupForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                installation = Installation.objects.select_for_update().get(pk=1)
                if installation.completed_at:
                    return redirect('backoffice:login')
                data = form.cleaned_data
                company = Company.objects.first() or Company(code='company-' + secrets.token_hex(5))
                for field in ('name', 'name_ka', 'address', 'phone'):
                    setattr(company, field, data[field])
                company.full_clean()
                company.save()
                owner = get_user_model().objects.create_superuser(data['username'], data['password'],
                    email=data['email'], name=data['first_name'], surname=data['last_name'])
                EmployeeAccess.objects.create(user=owner, company=company, application='both', all_branches=True)
                installation.completed_at = timezone.now()
                installation.save(update_fields=['completed_at'])
        except (IntegrityError, ValidationError):
            form.add_error(None, 'Setup could not be completed. Refresh and check the company and administrator details.')
        else:
            request.session.flush()
            messages.success(request, 'Your workspace is ready. Sign in with the administrator account you just created.')
            return redirect('backoffice:login')
    return render(request, 'backoffice/setup.html', {'form': form})


@never_cache
@sensitive_post_parameters('password')
def sign_in(request):
    if not Installation.objects.filter(pk=1, completed_at__isnull=False).exists():
        return redirect('backoffice:setup')
    if request.user.is_authenticated and backend_allowed(request.user):
        return redirect('backoffice:dashboard')
    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == 'POST':
        ip_ok = count_login_attempt('office:ip:' + client_address(request), 100)
        user_ok = count_login_attempt('office:user:' + request.POST.get('username', '')[:150].casefold(), 10)
        if not ip_ok or not user_ok:
            form.add_error(None, 'Too many sign-in attempts. Try again in five minutes.')
        elif form.is_valid():
            user = form.get_user()
            if backend_allowed(user):
                login(request, user)
                return redirect('backoffice:dashboard')
            form.add_error(None, 'This account cannot sign in to BackOffice.')
    return render(request, 'backoffice/login.html', {'form': form})


@require_POST
def sign_out(request):
    logout(request)
    return redirect('backoffice:login')


@backoffice()
def dashboard(request):
    branches = branches_for(request.user, request.company)
    today = timezone.localdate()
    can_report = allowed(request.user, 'view_reports')
    sales = Sale.objects.filter(register__location__in=branches) if can_report else Sale.objects.none()
    today_sales = sales.filter(occurred_at__date=today)
    total = today_sales.aggregate(value=Sum('total_minor'))['value'] or 0
    count = today_sales.count()
    start = today - timedelta(days=13)
    daily = dict(sales.filter(occurred_at__date__gte=start, occurred_at__date__lte=today)
        .annotate(day=TruncDate('occurred_at')).values('day').annotate(value=Sum('total_minor')).values_list('day', 'value'))
    maximum = max(daily.values(), default=0) or 1
    chart = [{'day': start + timedelta(days=i), 'amount': daily.get(start + timedelta(days=i), 0),
        'height': max(3, round(daily.get(start + timedelta(days=i), 0) * 100 / maximum))} for i in range(14)]
    context = {'nav': 'dashboard', 'today': today, 'total': total, 'transactions': count,
        'average': total // count if count else 0, 'branch_count': branches.filter(active=True).count(),
        'chart': chart, 'can_report': can_report, 'recent_sales': sales.select_related('register__location', 'cashier').order_by('-occurred_at')[:6],
        'branches': branches.order_by('name')[:4],
        'has_branch': Location.objects.filter(company=request.company, kind='branch', active=True).exists(),
        'has_product': Product.objects.filter(company=request.company).exists(),
        'has_pos': Register.objects.filter(location__company=request.company).exists(),
        'pending_count': EnrollmentRequest.objects.filter(status='pending', expires_at__gt=timezone.now()).count() if allowed(request.user, 'manage_locations') else 0,
        'low_stock': StockItem.objects.filter(location__in=branches, enabled=True, quantity_milli__lte=0).count() if allowed(request.user, 'manage_inventory') else None}
    return render(request, 'backoffice/dashboard.html', context)


SECTIONS = {
    'branches': (Location, LocationForm, 'Branches', 'branch', 'manage_locations'),
    'warehouses': (Location, LocationForm, 'Warehouses', 'warehouse', 'manage_locations'),
    'products': (Product, ProductForm, 'Products', None, 'manage_catalog'),
    'categories': (Category, CategoryForm, 'Categories', None, 'manage_catalog'),
    'stock': (StockItem, AssignmentForm, 'Inventory', None, 'manage_inventory'),
    'groups': (AccessGroup, GroupForm, 'Groups', None, 'manage_users'),
    'registers': (Register, RegisterForm, 'POS terminals', None, 'manage_locations'),
}


def section_info(request, section):
    if section not in SECTIONS: raise Http404()
    model, form, title, kind, permission = SECTIONS[section]
    if not allowed(request.user, permission): raise PermissionDenied()
    if section == 'stock':
        query = model.objects.filter(product__company=request.company).select_related('product', 'location')
    elif section == 'registers':
        query = model.objects.filter(location__company=request.company).select_related('location')
    else:
        query = model.objects.filter(company=request.company)
    if kind: query = query.filter(kind=kind)
    if section == 'products': query = query.select_related('category', 'home_location')
    return model, form, title, kind, query


def money(minor):
    return f'GEL {Decimal(minor) / 100:,.2f}'


@backoffice()
def listing(request, section):
    model, form, title, kind, query = section_info(request, section)
    search = request.GET.get('q', '').strip()[:150]
    if search:
        condition = Q(product__name__icontains=search) | Q(location__name__icontains=search) if section == 'stock' else Q(name__icontains=search)
        if section == 'products': condition |= Q(barcode__icontains=search) | Q(name_ka__icontains=search)
        query = query.filter(condition)
    page = Paginator(query.order_by('product__name', 'location__name') if section == 'stock' else query.order_by('name'), 25).get_page(request.GET.get('page'))
    columns = {'branches': ['Branch', 'Code', 'Address', 'Status'], 'warehouses': ['Warehouse', 'Code', 'Address', 'Status'],
        'products': ['Product', 'Barcode', 'Category', 'Price', 'Status'], 'categories': ['Category', 'Georgian name'],
        'stock': ['Product', 'Location', 'Quantity', 'Status'], 'groups': ['Group', 'Permissions'],
        'registers': ['POS terminal', 'Branch', 'Last seen', 'Status']}[section]
    rows = []
    for item in page:
        active = getattr(item, 'active', getattr(item, 'enabled', True))
        if kind: cells = [item.name, item.code, item.address or '—', 'Active' if active else 'Archived']
        elif section == 'products': cells = [item.name, item.barcode, item.category.name if item.category else '—', money(item.price_minor), 'Active' if active else 'Archived']
        elif section == 'categories': cells = [item.name, item.name_ka or '—']
        elif section == 'stock': cells = [item.product.name, item.location.name, f'{Decimal(item.quantity_milli)/1000:g} {item.product.get_unit_display()}', 'Active' if active else 'Disabled']
        elif section == 'groups': cells = [item.name, ', '.join(item.permissions.values_list('name', flat=True)) or '—']
        else: cells = [item.name, item.location.name, timezone.localtime(item.last_seen).strftime('%d %b %H:%M') if item.last_seen else 'Not connected yet', 'Active' if active else 'Disabled']
        rows.append({'id': item.pk, 'cells': cells, 'active': active, 'can_pair': section == 'registers' and active and not item.token_hash and not hasattr(item, 'deviceenrollment')})
    context = {'nav': section, 'section': section, 'title': title, 'columns': columns, 'rows': rows, 'page': page, 'q': search, 'can_add': True}
    if section == 'branches':
        context.update(pending=EnrollmentRequest.objects.filter(status='pending', expires_at__gt=timezone.now()).order_by('created_at')[:100],
            available_branches=Location.objects.filter(company=request.company, kind='branch', active=True).order_by('name'))
    return render(request, 'backoffice/list.html', context)


@backoffice()
def edit(request, section, identifier=None):
    model, form_class, title, kind, query = section_info(request, section)
    item = get_object_or_404(query, pk=identifier) if identifier else model()
    if kind: item.kind = kind
    kwargs = {'instance': item}
    kwargs['company'] = request.company
    form = form_class(request.POST or None, **kwargs)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                saved = form.save_for(request.user) if section == 'products' else form.save()
                if section == 'registers' and identifier is None:
                    code = generate_code(saved.location, request.user, saved)
                    return render(request, 'backoffice/pair.html', {'nav':'registers', 'code':code, 'branch':saved.location, 'register':saved})
        except (IntegrityError, ValidationError) as error:
            form.add_error(None, 'These details could not be saved. Check for duplicate codes or names.' if isinstance(error, IntegrityError) else '; '.join(error.messages))
        else:
            messages.success(request, 'Changes saved.')
            return redirect('backoffice:list', section=section)
    return render(request, 'backoffice/form.html', {'nav': section, 'title': ('Edit ' if identifier else 'Add ') + title.lower(), 'form': form,
        'back_url': 'backoffice:list', 'section': section, 'delete_id': identifier if section in {'categories', 'groups'} else None})


@require_POST
@backoffice()
def delete(request, section, identifier):
    if section not in {'categories', 'groups'}: raise Http404()
    *_, query = section_info(request, section)
    item = get_object_or_404(query, pk=identifier)
    try:
        item.delete()
    except ProtectedError:
        messages.error(request, 'This item is in use and cannot be deleted.')
    else:
        messages.success(request, 'Item removed.')
    return redirect('backoffice:list', section=section)


@backoffice('manage_inventory')
def adjust(request, identifier):
    stock = get_object_or_404(StockItem.objects.select_related('product', 'location'), pk=identifier, product__company=request.company)
    form = AdjustmentForm(request.POST or None, stock=stock)
    if request.method == 'POST' and form.is_valid():
        StockAdjustment.objects.create(stock_item=stock, quantity_milli=int(form.cleaned_data['quantity']*1000), reason=form.cleaned_data['reason'], actor=request.user)
        messages.success(request, 'Stock adjustment recorded.')
        return redirect('backoffice:list', section='stock')
    return render(request, 'backoffice/form.html', {'nav': 'stock', 'title': 'Adjust inventory', 'subtitle': f'{stock.product.name} · {stock.location.name}', 'form': form, 'back_url': 'backoffice:list', 'section': 'stock'})


@backoffice('manage_users')
def users(request):
    query = get_user_model().objects.filter(Q(pos_access__company=request.company) | Q(is_superuser=True)).distinct()
    search = request.GET.get('q', '').strip()[:150]
    if search: query = query.filter(Q(username__icontains=search) | Q(name__icontains=search) | Q(email__icontains=search))
    page = Paginator(query.select_related('pos_access').order_by('username'), 25).get_page(request.GET.get('page'))
    return render(request, 'backoffice/users.html', {'nav': 'users', 'page': page, 'q': search})


@backoffice('manage_users')
@sensitive_post_parameters('password', 'password_confirm')
def user_edit(request, identifier=None):
    user = get_object_or_404(get_user_model().objects.filter(Q(pos_access__company=request.company) | Q(is_superuser=True)), pk=identifier) if identifier else None
    if user and user.is_superuser and not request.user.is_superuser: raise PermissionDenied()
    form = EmployeeForm(request.POST or None, company=request.company, user=user, actor=request.user)
    if request.method == 'POST' and form.is_valid():
        try:
            saved = form.save()
        except IntegrityError:
            form.add_error(None, 'This username already exists.')
        else:
            if saved.pk == request.user.pk: update_session_auth_hash(request, saved)
            messages.success(request, 'User access saved.')
            return redirect('backoffice:users')
    return render(request, 'backoffice/form.html', {'nav': 'users', 'title': 'Edit user' if user else 'Add user', 'form': form, 'back_url': 'backoffice:users'})


@backoffice()
def company_settings(request):
    if not request.user.is_superuser: raise PermissionDenied()
    form = CompanyForm(request.POST or None, instance=request.company)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Company settings saved.')
        return redirect('backoffice:company')
    return render(request, 'backoffice/form.html', {'nav': 'company', 'title': 'Company settings', 'subtitle': 'One workspace for your company, across every branch.', 'form': form, 'back_url': 'backoffice:dashboard'})


@backoffice()
@sensitive_post_parameters()
def password(request):
    form = PasswordChangeForm(request.user, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        update_session_auth_hash(request, form.save())
        messages.success(request, 'Password changed.')
        return redirect('backoffice:dashboard')
    return render(request, 'backoffice/form.html', {'title': 'Change password', 'form': form, 'back_url': 'backoffice:dashboard'})


@require_POST
@backoffice('manage_locations')
def pair(request, identifier):
    branch = get_object_or_404(Location, pk=identifier, company=request.company, kind='branch', active=True)
    code = generate_code(branch, request.user)
    return render(request, 'backoffice/pair.html', {'nav': 'branches', 'code': code, 'branch': branch})


@require_POST
@backoffice('manage_locations')
def review(request, identifier):
    branch = None
    try:
        if request.POST.get('decision') not in {'approve', 'reject'}: raise ValidationError('Choose approve or reject.')
        if request.POST.get('branch'):
            branch = get_object_or_404(Location, pk=UUID(request.POST['branch']), company=request.company, kind='branch', active=True)
        review_request(identifier, request.user, request.POST['decision'] == 'approve', branch)
    except (ValidationError, ValueError, EnrollmentRequest.DoesNotExist) as error:
        messages.error(request, '; '.join(error.messages) if isinstance(error, ValidationError) else 'This request or branch is no longer available.')
    else:
        messages.success(request, 'POS request reviewed. The cashier can check approval now.')
    return redirect('backoffice:list', section='branches')


@backoffice('view_reports')
def sales(request):
    query = Sale.objects.filter(register__location__in=branches_for(request.user, request.company)).select_related('register__location', 'cashier').order_by('-occurred_at')
    return render(request, 'backoffice/sales.html', {'nav': 'sales', 'page': Paginator(query, 25).get_page(request.GET.get('page'))})


@backoffice('view_reports')
def sale(request, identifier):
    item = get_object_or_404(Sale.objects.select_related('register__location', 'cashier'), pk=identifier, register__location__in=branches_for(request.user, request.company))
    return render(request, 'backoffice/sale.html', {'nav': 'sales', 'sale': item, 'lines': item.lines.all()})


@backoffice('supervise_basket')
def checkouts(request):
    from commerce.models import BasketCommand
    branches = branches_for(request.user, request.company).order_by('name')
    try:
        branch = get_object_or_404(branches, pk=UUID(request.GET['branch'])) if request.GET.get('branch') else None
    except ValueError: raise Http404() from None
    baskets, page = [], None
    if branch:
        baskets = list(scoped_baskets(request.user, LiveBasket.objects.select_related('register__location', 'operator')).filter(register__location=branch).order_by('register__name'))
        for basket in baskets: basket.lines = json.loads(basket.lines_json)
        history = BasketCommand.objects.filter(register__location=branch).select_related('register','requested_by').order_by('-created_at')
        page = Paginator(history, 25).get_page(request.GET.get('page'))
    return render(request, 'backoffice/checkouts.html', {'nav':'checkouts', 'branches':branches, 'branch':branch,
        'baskets':baskets, 'page':page, 'now':timezone.now(), 'fresh_after':timezone.now()-timedelta(seconds=15)})

@backoffice('supervise_basket')
def checkout(request, identifier):
    snapshot = get_object_or_404(scoped_baskets(request.user, LiveBasket.objects.select_related('register__location', 'operator')), register_id=identifier)
    if request.method == 'POST':
        try:
            request_removal(request.user, snapshot.register_id, request.POST.get('basket_id'), int(request.POST.get('revision', '-1')), request.POST.get('line_key'), request.POST.get('reason'))
        except (ValidationError, ValueError) as error:
            messages.error(request, '; '.join(error.messages) if isinstance(error, ValidationError) else 'Refresh and try again.')
        else: messages.success(request, 'Removal requested. Confirmation from the POS will appear in history.')
    from django.urls import reverse
    return redirect(reverse('backoffice:checkouts') + '?branch=' + str(snapshot.register.location_id))

@require_POST
@backoffice('manage_locations')
def register_pair(request, identifier):
    register = get_object_or_404(Register.objects.select_related('location'), pk=identifier, location__company=request.company)
    try: code = generate_code(register.location, request.user, register)
    except ValidationError as error:
        messages.error(request, '; '.join(error.messages))
        return redirect('backoffice:list', section='registers')
    return render(request, 'backoffice/pair.html', {'nav':'registers', 'code':code, 'branch':register.location, 'register':register})
