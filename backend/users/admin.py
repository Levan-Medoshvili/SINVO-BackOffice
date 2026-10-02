from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.contrib.auth.models import Group as DjangoGroup
from commerce.models import EmployeeAccess
from commerce.forms import EmployeeAccessForm
from .models import User


class CreateUserForm(UserCreationForm):
    class Meta:
        model = User
        fields = ("username", "name", "surname", "email")


class ChangeUserForm(UserChangeForm):
    class Meta:
        model = User
        fields = "__all__"


class EmployeeAccessInline(admin.StackedInline):
    model = EmployeeAccess
    form = EmployeeAccessForm
    fields = ("company", "application", "all_branches", "branches", "groups", "permissions")
    filter_horizontal = ("branches", "groups", "permissions")
    extra = 1
    max_num = 1
    can_delete = False


@admin.register(User)
class CustomUserAdmin(BaseUserAdmin):
    form = ChangeUserForm
    add_form = CreateUserForm
    list_display = ("username", "name", "surname", "is_staff", "is_active")
    list_filter = ("is_active", "pos_access__application", "pos_access__company")
    readonly_fields = ("date_joined", "last_login")
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Personal information", {"fields": ("name", "surname", "email", "mobile")}),
        ("Platform access", {"fields": ("is_active", "is_superuser"), "description": "Application and branch access are configured below. Platform superuser is unrestricted administration."}),
        ("History", {"fields": ("date_joined", "last_login")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("username", "name", "surname", "email", "password1", "password2")}),)
    inlines = [EmployeeAccessInline]
    search_fields = ("username", "name", "surname")
    ordering = ("username",)
    filter_horizontal = ()
    def has_module_permission(self, request): return request.user.is_active and request.user.is_superuser
    def has_view_permission(self, request, obj=None): return self.has_module_permission(request)
    def has_add_permission(self, request): return self.has_module_permission(request)
    def has_change_permission(self, request, obj=None): return self.has_module_permission(request)
    def has_delete_permission(self, request, obj=None): return False
    def save_model(self, request, obj, form, change):
        if obj.is_superuser: obj.is_staff = True
        super().save_model(request, obj, form, change)


if admin.site.is_registered(DjangoGroup): admin.site.unregister(DjangoGroup)
