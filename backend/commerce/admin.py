from django.contrib import admin
from django.conf import settings
from django.http import HttpResponse
from .models import Company, Location, Category, Product, PriceRevision, StockItem, StockAdjustment, StockMovement, Register, Sale, SaleLine


class PlatformAdmin(admin.ModelAdmin):
    """The pilot BackOffice is for platform administrators, not unscoped tenant staff."""
    def has_module_permission(self, request): return request.user.is_active and request.user.is_superuser
    def has_view_permission(self, request, obj=None): return self.has_module_permission(request)
    def has_add_permission(self, request): return self.has_module_permission(request)
    def has_change_permission(self, request, obj=None): return self.has_module_permission(request)
    def has_delete_permission(self, request, obj=None): return False


class HistoryAdmin(PlatformAdmin):
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False


@admin.register(Company)
class CompanyAdmin(PlatformAdmin):
    list_display = ["name", "code", "currency", "active"]
    def has_add_permission(self, request): return False


@admin.register(Location)
class LocationAdmin(PlatformAdmin):
    list_display = ["name", "company", "kind", "address", "active"]
    list_filter = ["company", "kind", "active"]


@admin.register(Category)
class CategoryAdmin(PlatformAdmin):
    list_display = ["name", "name_ka", "company"]


@admin.register(Product)
class ProductAdmin(PlatformAdmin):
    list_display = ["name", "barcode", "company", "home_location", "price_minor", "active"]
    list_filter = ["company", "active"]
    search_fields = ["name", "barcode"]


@admin.register(StockItem)
class StockItemAdmin(PlatformAdmin):
    list_display = ["product", "location", "quantity_milli", "enabled"]
    list_filter = ["location__company", "location"]
    readonly_fields = ["quantity_milli"]
    def get_readonly_fields(self, request, obj=None):
        return ["product", "location", "quantity_milli"] if obj else ["quantity_milli"]


@admin.register(StockAdjustment)
class StockAdjustmentAdmin(PlatformAdmin):
    list_display = ["stock_item", "quantity_milli", "reason", "actor", "created_at"]
    def has_change_permission(self, request, obj=None): return False
    def save_model(self, request, obj, form, change):
        obj.actor = request.user
        super().save_model(request, obj, form, change)


@admin.register(Register)
class RegisterAdmin(PlatformAdmin):
    list_display = ["name", "location", "code", "active", "last_seen"]
    exclude = ["token_hash"]
    readonly_fields = ["last_seen"]
    actions = ["issue_credential"]
    def get_readonly_fields(self, request, obj=None):
        return ["location", "last_seen"] if obj else ["last_seen"]
    @admin.action(description="Issue a new connection credential for one register")
    def issue_credential(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(request, "Select exactly one register.", level="error")
            return
        token = queryset.get().issue_token()
        response = HttpResponse("Copy this credential into Cashier. The old credential is now revoked.\n\n" + token + "\n", content_type="text/plain")
        response["Cache-Control"] = "no-store"
        response["Referrer-Policy"] = "no-referrer"
        return response


class SaleLineInline(admin.TabularInline):
    model = SaleLine
    extra = 0
    can_delete = False
    readonly_fields = ["product", "price_revision", "name", "barcode", "quantity_milli", "unit_price_minor", "total_minor"]
    def has_add_permission(self, request, obj=None): return False


@admin.register(Sale)
class SaleAdmin(HistoryAdmin):
    list_display = ["client_id", "register", "occurred_at", "received_at", "total_minor", "cash_received_minor"]
    list_filter = ["register__location__company", "register__location"]
    inlines = [SaleLineInline]


@admin.register(StockMovement)
class MovementAdmin(HistoryAdmin):
    list_display = ["stock_item", "quantity_milli", "reason", "created_at"]


admin.site.site_header = f"{settings.SIMPLEPOS_BRAND} BackOffice"
admin.site.site_title = settings.SIMPLEPOS_BRAND
admin.site.index_title = "Pilot administration"
from decimal import Decimal
import json
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from .access import backend_allowed, can_supervise
from .forms import AccessGroupForm
from .models import AccessGroup, LiveBasket, BasketCommand
from .supervision import scoped_baskets, request_removal


@admin.register(AccessGroup)
class AccessGroupAdmin(PlatformAdmin):
    form = AccessGroupForm
    list_display = ["name", "company"]
    list_filter = ["company"]
    filter_horizontal = ["permissions"]


class ScopedBranchFilter(admin.SimpleListFilter):
    title = "branch"
    parameter_name = "branch"
    def lookups(self, request, model_admin):
        allowed = scoped_baskets(request.user, LiveBasket.objects.all()).values_list("register__location_id", flat=True)
        return [(str(branch.pk), str(branch)) for branch in Location.objects.filter(pk__in=allowed).select_related("company").order_by("name")]
    def queryset(self, request, queryset):
        if not self.value(): return queryset
        try:
            from uuid import UUID
            return queryset.filter(register__location_id=UUID(self.value()))
        except ValueError: return queryset.none()


@admin.register(LiveBasket)
class LiveBasketAdmin(admin.ModelAdmin):
    list_display = ["register", "branch", "operator", "state", "seen_at"]
    list_filter = [ScopedBranchFilter]
    search_fields = ["register__name", "register__location__name"]
    actions = None
    def branch(self, obj): return obj.register.location.name
    def has_module_permission(self, request): return can_supervise(request.user)
    def has_view_permission(self, request, obj=None): return can_supervise(request.user, obj.register.location if obj else None)
    def has_change_permission(self, request, obj=None): return False
    def has_add_permission(self, request): return False
    def has_delete_permission(self, request, obj=None): return False
    def get_queryset(self, request):
        return scoped_baskets(request.user, super().get_queryset(request).select_related("register__location", "operator"))
    def get_urls(self):
        return [path("<path:object_id>/remove/", self.admin_site.admin_view(self.remove_view), name="commerce_livebasket_remove")] + super().get_urls()
    def change_view(self, request, object_id, form_url="", extra_context=None):
        obj = get_object_or_404(self.get_queryset(request), pk=object_id)
        if not self.has_view_permission(request, obj): raise PermissionDenied()
        lines = json.loads(obj.lines_json)
        for line in lines:
            line["quantity"] = Decimal(line["quantity_milli"]) / 1000
            line["amount"] = Decimal(line["total_minor"]) / 100
        commands = BasketCommand.objects.filter(register=obj.register).select_related("requested_by").order_by("-created_at")[:30]
        return TemplateResponse(request, "admin/commerce/live_basket.html", {**self.admin_site.each_context(request),
            "title": f"Live checkout — {obj.register.name}", "opts": self.model._meta, "original": obj,
            "lines": lines, "commands": commands, "total": sum(line["amount"] for line in lines),
            "fresh": (timezone.now() - obj.seen_at).total_seconds() <= 15,
            "remove_url": reverse("admin:commerce_livebasket_remove", args=[obj.pk])})
    def remove_view(self, request, object_id):
        if request.method != "POST": raise PermissionDenied()
        obj = get_object_or_404(self.get_queryset(request), pk=object_id)
        try:
            request_removal(request.user, obj.register_id, request.POST.get("basket_id"), int(request.POST.get("revision", "-1")),
                request.POST.get("line_key"), request.POST.get("reason", ""))
            self.message_user(request, "Removal requested. Refresh to see the POS confirmation. The item remains until the POS confirms it.")
        except (ValidationError, ValueError) as error:
            self.message_user(request, "; ".join(error.messages) if isinstance(error, ValidationError) else "Invalid request. Refresh and try again.", level="error")
        return redirect("admin:commerce_livebasket_change", object_id)


@admin.register(BasketCommand)
class BasketCommandAdmin(HistoryAdmin):
    list_display = ["register", "product_name", "requested_by", "reason", "status", "created_at", "completed_at"]
    def has_module_permission(self, request): return can_supervise(request.user)
    def get_queryset(self, request):
        allowed = scoped_baskets(request.user, LiveBasket.objects.all()).values_list("register_id", flat=True)
        return super().get_queryset(request).filter(register_id__in=allowed)
    def has_view_permission(self, request, obj=None): return can_supervise(request.user, obj.register.location if obj else None)


admin.site.index_title = "Administration"
admin.site.has_permission = lambda request: backend_allowed(request.user)
