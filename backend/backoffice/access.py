from functools import wraps
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from commerce.access import backend_allowed, employee_access, permission_codes
from commerce.models import Company, Installation, Location

def allowed(user, permission):
    return backend_allowed(user) and (user.is_superuser or permission in permission_codes(employee_access(user)))

def backoffice(permission=None):
    def decorate(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not Installation.objects.filter(pk=1, completed_at__isnull=False).exists(): return redirect('backoffice:setup')
            if not request.user.is_authenticated: return redirect('backoffice:login')
            if not backend_allowed(request.user) or (permission and not allowed(request.user, permission)): raise PermissionDenied()
            request.company = Company.objects.get()
            response = view(request, *args, **kwargs)
            response['Cache-Control'] = 'no-store'
            return response
        return wrapped
    return decorate

def branches_for(user, company):
    branches = Location.objects.filter(company=company, kind='branch')
    if user.is_superuser: return branches
    access = employee_access(user)
    return branches if access and access.all_branches else branches.filter(employeeaccess=access)

def shell(request):
    permissions = {code: allowed(request.user, code) for code in ['manage_catalog','manage_locations','manage_users','manage_inventory','view_reports','supervise_basket']} if request.user.is_authenticated else {}
    return {'brand': settings.SIMPLEPOS_BRAND, 'company': getattr(request, 'company', None), 'access_flags': permissions}
