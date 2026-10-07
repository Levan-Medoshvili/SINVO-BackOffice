from django.conf import settings
from django.db import connection, DatabaseError
from django.http import JsonResponse
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import StockItem, Installation, Company
from .services import receive_sale, SaleRejected, SaleConflict


def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        installation = Installation.objects.filter(pk=1).first()
        company = Company.objects.first()
    except DatabaseError:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok", "api_version": 1, "build_revision": settings.SIMPLEPOS_BUILD_REVISION, "company_id": str(company.pk) if company else None, "installation_id": str(installation.public_id) if installation else None, "setup_complete": bool(installation and installation.completed_at), "enrollment_version": 1})


@api_view(["GET"])
def catalog(request):
    register = request.auth
    company = register.location.company
    rows = StockItem.objects.filter(location=register.location, enabled=True, product__active=True,
        product__company=company).select_related("product__current_price", "product__category", "product__subcategory").order_by("product__name", "product_id")
    # Older Cashiers reject unknown units for the entire catalog. Keep them usable
    # during a staged rollout; v0.5 declares liter support explicitly.
    if 'liter' not in request.query_params.get('units', '').split(','):
        rows = rows.exclude(product__unit='liter')
    products = []
    for stock in rows:
        p = stock.product
        if not p.current_price_id:
            continue
        products.append({"id": str(p.pk), "barcode": p.barcode, "name": p.name, "name_ka": p.name_ka,
            "category": p.category.name if p.category else "", "category_ka": p.category.name_ka if p.category else "",
            "subcategory": p.subcategory.name if p.subcategory else "", "subcategory_ka": p.subcategory.name_ka if p.subcategory else "",
            "unit": p.unit, "price_minor": p.current_price.price_minor, "price_id": str(p.current_price_id)})
    from .advertisements import playlist
    return Response({"advertisements":playlist(register.location), "api_version": 1, "generated_at": timezone.now().isoformat(), "brand": settings.SIMPLEPOS_BRAND,
        "company": {"id": str(company.pk), "name": company.name, "currency": company.currency, "advertisement": company.advertisement, "removal_notice_minutes": company.removal_notice_minutes},
        "branch": {"id": str(register.location_id), "name": register.location.name},
        "register": {"id": str(register.pk), "name": register.name}, "products": products})


@api_view(["POST"])
def sales(request):
    batch = request.data.get("sales") if isinstance(request.data, dict) else None
    if not isinstance(batch, list) or not 1 <= len(batch) <= 100:
        return Response({"detail": "Send 1–100 sales."}, status=400)
    results = []
    for item in batch:
        client_id = item.get("id") if isinstance(item, dict) else None
        try:
            saved, duplicate = receive_sale(request.auth, item)
            results.append({"id": str(saved.client_id), "status": "acknowledged", "server_id": str(saved.pk), "duplicate": duplicate})
        except SaleConflict as exc:
            results.append({"id": client_id, "status": "conflict", "detail": str(exc)})
        except SaleRejected as exc:
            results.append({"id": client_id, "status": "rejected", "detail": str(exc)})
    return Response({"results": results})
