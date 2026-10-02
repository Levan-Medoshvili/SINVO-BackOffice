"""Device-confirmed basket commands. A manager request never edits a completed sale."""
import json
from datetime import timedelta
from uuid import UUID
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .access import can_supervise, decode_authorization, operator_data
from .models import Register, LiveBasket, BasketCommand, PriceRevision, StockItem


def scoped_baskets(user, queryset):
    if user.is_superuser: return queryset
    access = getattr(user, "pos_access", None)
    if not can_supervise(user) or not access: return queryset.none()
    queryset = queryset.filter(register__location__company_id=access.company_id)
    return queryset if access.all_branches else queryset.filter(register__location__in=access.branches.all())


def integer(value, low=0, high=9007199254740991):
    if type(value) is not int or not low <= value <= high: raise ValueError("Invalid quantity or revision.")
    return value


def clean_basket(data, register):
    if not isinstance(data, dict): raise ValueError("Invalid basket.")
    basket_id = UUID(data["id"])
    revision = integer(data["revision"])
    state = data["state"]
    if state not in {"active", "empty", "locked", "completed"}: raise ValueError("Invalid basket state.")
    lines = data["lines"]
    if not isinstance(lines, list) or len(lines) > 250: raise ValueError("Invalid basket lines.")
    if state in {"empty", "completed"} and lines: raise ValueError("Completed baskets cannot be edited.")
    prices = {str(p.pk): p for p in PriceRevision.objects.select_related("product").filter(
        pk__in=[UUID(line["price_id"]) for line in lines], product__company_id=register.location.company_id)}
    assigned = set(str(i) for i in StockItem.objects.filter(location=register.location).values_list("product_id", flat=True))
    clean, keys = [], set()
    for line in lines:
        price = prices.get(line["price_id"])
        if not price or str(price.product_id) != line["id"] or line["id"] not in assigned: raise ValueError("Product is not assigned to this branch.")
        key = line["id"] + ":" + line["price_id"]
        quantity = integer(line["quantity_milli"], 1, 1000000000)
        if key in keys or key != line["key"] or integer(line["price_minor"]) != price.price_minor: raise ValueError("Invalid basket line.")
        if price.product.unit == "piece" and quantity % 1000: raise ValueError("Invalid piece quantity.")
        keys.add(key)
        clean.append({"key": key, "id": str(price.product_id), "price_id": str(price.pk), "name": price.product.name,
            "barcode": price.product.barcode, "quantity_milli": quantity, "price_minor": price.price_minor,
            "total_minor": (quantity * price.price_minor + 500) // 1000})
    return basket_id, revision, state, clean


@api_view(["POST"])
def basket_sync(request):
    register = request.auth
    try:
        data = request.data
        basket_id, revision, state, lines = clean_basket(data["basket"], register)
        acknowledgements = data.get("acknowledgements", [])
        if not isinstance(acknowledgements, list) or len(acknowledgements) > 100: raise ValueError("Invalid acknowledgements.")
        acks = []
        for ack in acknowledgements:
            identifier = UUID(ack["id"])
            if ack["status"] not in {"applied", "rejected"}: raise ValueError("Invalid command result.")
            acks.append((identifier, ack["status"], str(ack.get("detail", ""))[:250]))
    except (ValueError, TypeError, KeyError, AttributeError):
        return Response({"detail": "Invalid basket snapshot or acknowledgement."}, status=400)
    operator, policy, denied = None, None, False
    authorization = data["basket"].get("authorization")
    if authorization:
        try:
            session = decode_authorization(authorization, register)
            policy = operator_data(session)
            operator = session.user
        except PermissionDenied: denied = True
    elif state == "active": denied = True
    if denied: state = "locked"
    now = timezone.now()
    with transaction.atomic():
        Register.objects.select_for_update().get(pk=register.pk)
        snapshot = LiveBasket.objects.filter(register=register).first()
        if snapshot and (revision < snapshot.revision or (revision == snapshot.revision and basket_id != snapshot.basket_id)):
            return Response({"detail": "Basket revision is older than the server snapshot. Keep this device's database; contact the administrator."}, status=409)
        snapshot, _ = LiveBasket.objects.update_or_create(register=register, defaults={"basket_id": basket_id,
            "revision": revision, "state": state, "lines_json": json.dumps(lines), "operator": operator})
        accepted = []
        for identifier, status, detail in acks:
            command = BasketCommand.objects.filter(pk=identifier, register=register).first()
            if not command: continue
            if command.status in {"pending", "expired"}:
                command.status, command.result_detail, command.completed_at = status, detail, now
                command.save(update_fields=["status", "result_detail", "completed_at"])
            accepted.append(str(command.pk))
        BasketCommand.objects.filter(register=register, status="pending", expires_at__lte=now).update(status="expired", completed_at=now)
        commands = [{"id": str(c.pk), "basket_id": str(c.basket_id), "expected_revision": c.expected_revision,
            "line_key": c.line_key, "reason": c.reason, "manager_name": c.requested_by.username, "expires_at": c.expires_at.isoformat()}
            for c in BasketCommand.objects.filter(register=register, status="pending").select_related("requested_by").order_by("created_at")[:20]]
    return Response({"commands": commands, "acknowledged": accepted, "operator": policy, "access_denied": denied})


@transaction.atomic
def request_removal(user, register_id, basket_id, revision, line_key, reason):
    register = Register.objects.select_for_update().select_related("location__company").get(pk=register_id)
    if not can_supervise(user, register.location): raise PermissionDenied()
    snapshot = LiveBasket.objects.get(register=register)
    now = timezone.now()
    if not register.active or not register.location.active or not register.location.company.active:
        raise ValidationError("This register is disabled.")
    if snapshot.state != "active" or snapshot.seen_at < now - timedelta(seconds=15):
        raise ValidationError("The register is locked, offline, or has no active customer. Refresh before trying again.")
    if str(snapshot.basket_id) != str(basket_id) or snapshot.revision != integer(revision):
        raise ValidationError("The basket changed. Refresh and select the item again.")
    line = next((line for line in json.loads(snapshot.lines_json) if line["key"] == line_key), None)
    if not line: raise ValidationError("This item is no longer in the basket.")
    if not isinstance(reason, str) or not 3 <= len(reason.strip()) <= 250: raise ValidationError("Enter a reason between 3 and 250 characters.")
    if BasketCommand.objects.filter(register=register, status="pending", expires_at__gt=now).exists():
        raise ValidationError("Wait for the previous request to be confirmed or expire, then refresh.")
    return BasketCommand.objects.create(register=register, basket_id=snapshot.basket_id, expected_revision=revision,
        line_key=line_key, product_name=line["name"], reason=reason.strip(), requested_by=user, expires_at=now + timedelta(seconds=90))
