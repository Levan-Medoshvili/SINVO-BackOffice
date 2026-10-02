import hashlib
import json
from uuid import UUID
from django.db import transaction, models
from django.conf import settings
from django.core.exceptions import PermissionDenied
from .access import decode_authorization
from django.utils.dateparse import parse_datetime
from django.utils.timezone import is_aware
from .models import Register, Sale, SaleLine, StockItem, StockMovement, PriceRevision


class SaleRejected(ValueError):
    pass


class SaleConflict(SaleRejected):
    pass


def integer(value, name, minimum=0, maximum=9000000000000):
    if type(value) is not int or not minimum <= value <= maximum:
        raise SaleRejected(f"Invalid {name}.")
    return value


def identifier(value):
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        raise SaleRejected("Invalid identifier.") from None


@transaction.atomic
def receive_sale(register, payload):
    if not isinstance(payload, dict):
        raise SaleRejected("Sale must be an object.")
    expected = {"id", "occurred_at", "currency", "payment_method", "cash_received_minor", "total_minor", "lines"}
    if set(payload) not in (expected, expected | {"cashier_authorization"}) or payload["payment_method"] != "cash" or payload["currency"] != "GEL":
        raise SaleRejected("This pilot accepts cash sales in GEL using contract v1.")
    client_id = identifier(payload["id"])
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    # Serialize submissions from one register; stock rows are locked in a stable order below.
    Register.objects.select_for_update().get(pk=register.pk)
    existing = Sale.objects.filter(register=register, client_id=client_id).first()
    if existing:
        if existing.payload_hash != digest:
            raise SaleConflict("This sale ID already exists with different contents; review is required.")
        return existing, True
    try:
        occurred_at = parse_datetime(payload["occurred_at"])
    except (ValueError, TypeError):
        occurred_at = None
    if occurred_at is None or not is_aware(occurred_at):
        raise SaleRejected("occurred_at must include a time-zone offset.")
    session = None
    if "cashier_authorization" in payload:
        try: session = decode_authorization(payload["cashier_authorization"], register, occurred_at)
        except PermissionDenied as exc: raise SaleRejected(str(exc)) from None
    elif not settings.SIMPLEPOS_ALLOW_LEGACY_SALES:
        raise SaleRejected("Cashier sign-in is required. Retain legacy offline sales for administrator-assisted migration.")
    lines = payload["lines"]
    if not isinstance(lines, list) or not 1 <= len(lines) <= 250:
        raise SaleRejected("A sale must have 1–250 lines.")
    total = integer(payload["total_minor"], "total")
    cash = integer(payload["cash_received_minor"], "cash received", minimum=total)
    prepared, seen, calculated = [], set(), 0
    for row in lines:
        if not isinstance(row, dict) or set(row) != {"product_id", "price_id", "quantity_milli", "unit_price_minor", "total_minor"}:
            raise SaleRejected("Invalid sale line.")
        product_id = identifier(row["product_id"])
        price_id = identifier(row["price_id"])
        key = (product_id, price_id)
        if key in seen:
            raise SaleRejected("Duplicate product/price line.")
        seen.add(key)
        quantity = integer(row["quantity_milli"], "quantity", 1, 1000000000)
        try:
            revision = PriceRevision.objects.select_related("product").get(pk=price_id, product_id=product_id,
                product__company_id=register.location.company_id)
        except PriceRevision.DoesNotExist:
            raise SaleRejected("Product or published price is not available to this company.") from None
        if revision.product.unit == "piece" and quantity % 1000:
            raise SaleRejected("Piece quantities must be whole numbers.")
        unit_price = integer(row["unit_price_minor"], "price", 0, 100000000)
        line_total = integer(row["total_minor"], "line total")
        if unit_price != revision.price_minor or line_total != (unit_price * quantity + 500) // 1000:
            raise SaleRejected("Price or total does not match the published price revision.")
        calculated += line_total
        prepared.append((revision, quantity, line_total))
    if calculated != total:
        raise SaleRejected("Sale total does not match its lines.")
    stocks = {s.product_id: s for s in StockItem.objects.select_for_update().filter(
        location=register.location, product_id__in=[p.product_id for p, _, _ in prepared]).order_by("product_id")}
    if any(p.product_id not in stocks for p, _, _ in prepared):
        raise SaleRejected("A product is not assigned to this branch.")
    sale = Sale.objects.create(register=register, client_id=client_id, payload_hash=digest,
        occurred_at=occurred_at, total_minor=total, cash_received_minor=cash, currency="GEL",
        cashier=session.user if session else None, cashier_session=session)
    for revision, quantity, line_total in prepared:
        product, stock = revision.product, stocks[revision.product_id]
        line = SaleLine.objects.create(sale=sale, product=product, price_revision=revision, name=product.name,
            barcode=product.barcode, quantity_milli=quantity, unit_price_minor=revision.price_minor, total_minor=line_total)
        StockItem.objects.filter(pk=stock.pk).update(quantity_milli=models.F("quantity_milli") - quantity)
        StockMovement.objects.create(stock_item=stock, quantity_milli=-quantity, reason="cash_sale", sale_line=line)
    # Negative stock is retained for review: an offline completed sale must not disappear.
    return sale, False
