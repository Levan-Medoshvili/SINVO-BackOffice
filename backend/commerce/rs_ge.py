"""Read-only RS.ge SOAP adapter and atomic local inventory receiving."""
import hashlib
import re
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree as XML
from defusedxml import ElementTree
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from .integration_secrets import decrypt
from .models import Installation, Product, ReceivedWaybill, StockItem, StockMovement

ENDPOINT = 'https://services.rs.ge/WayBillService/WayBillService.asmx'
SOAP, NS, XSI = 'http://schemas.xmlsoap.org/soap/envelope/', 'http://tempuri.org/', 'http://www.w3.org/2001/XMLSchema-instance'
MAX_RESPONSE = 8 * 1024 * 1024

def local(tag): return tag.rsplit('}', 1)[-1]
def children(node): return {local(child.tag): (child.text or '').strip() for child in node if not len(child)}

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None

def parse_xml(raw):
    try:
        if len(raw) > MAX_RESPONSE: raise ValueError()
        root = ElementTree.fromstring(raw, forbid_dtd=True, forbid_entities=True, forbid_external=True)
        stack = [(root, 0)]
        count = 0
        while stack:
            element, depth = stack.pop(); count += 1
            if depth > 30 or count > 100000: raise ValueError()
            stack.extend((child, depth + 1) for child in element)
        return root
    except Exception: raise ValidationError('RS.ge returned invalid or oversized XML.') from None

class RSClient:
    def __init__(self, config): self.config = config
    def call(self, method, values=None):
        if not self.config.enabled: raise ValidationError('Enable RS.ge in Integrations first.')
        if method not in {'chek_service_user', 'get_waybill', 'get_buyer_waybills_ex', 'get_waybill_units'}:
            raise ValidationError('Unsupported read operation.')
        envelope = XML.Element(f'{{{SOAP}}}Envelope')
        operation = XML.SubElement(XML.SubElement(envelope, f'{{{SOAP}}}Body'), f'{{{NS}}}{method}')
        for key, value in {'su': self.config.service_user, 'sp': decrypt(self.config.password_encrypted), **(values or {})}.items():
            element = XML.SubElement(operation, f'{{{NS}}}{key}')
            if value is None: element.set(f'{{{XSI}}}nil', 'true')
            else: element.text = str(value)
        request = urllib.request.Request(ENDPOINT, data=XML.tostring(envelope, encoding='utf-8', xml_declaration=True),
            headers={'Content-Type': 'text/xml; charset=utf-8', 'SOAPAction': f'"{NS}{method}"'})
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=20) as response:
                raw = response.read(MAX_RESPONSE + 1)
        except (OSError, urllib.error.URLError):
            raise ValidationError('RS.ge could not be reached or rejected the request. Check service credentials and try again.') from None
        root = parse_xml(raw)
        if any(local(node.tag) == 'Fault' for node in root.iter()): raise ValidationError('RS.ge returned a service error. Check the integration settings.')
        result = next((node for node in root.iter() if local(node.tag) == method + 'Result'), None)
        if result is None: raise ValidationError('RS.ge returned an unexpected response.')
        if len(result): return result[0]
        if method == 'chek_service_user':
            if (result.text or '').strip().lower() not in {'true', '1'}: raise ValidationError('RS.ge rejected the service user or password.')
            return True
        if (result.text or '').strip().startswith('<'): return parse_xml(result.text.encode())
        raise ValidationError('RS.ge did not return a document.')

    def incoming(self, start, end, confirmed=0):
        values = dict(itypes='', seller_tin='', statuses='1,2', car_number='', begin_date_s=None, begin_date_e=None,
            create_date_s=start.isoformat() + 'T00:00:00', create_date_e=end.isoformat() + 'T23:59:59', driver_tin='',
            delivery_date_s=None, delivery_date_e=None, full_amount=None, waybill_number='', close_date_s=None,
            close_date_e=None, s_user_ids='', comment='', is_confirmed=confirmed)
        root = self.call('get_buyer_waybills_ex', values)
        return [children(node) for node in root.iter() if local(node.tag) == 'WAYBILL'][:200]

    def detail(self, identifier):
        if not re.fullmatch(r'[1-9][0-9]{0,9}', str(identifier)) or int(identifier) > 2147483647: raise ValidationError('Enter a valid RS.ge waybill ID.')
        root = self.call('get_waybill', {'waybill_id': identifier})
        if local(root.tag) != 'WAYBILL': raise ValidationError('RS.ge did not return the requested waybill.')
        fields = children(root)
        if fields.get('ID') != str(identifier): raise ValidationError('The returned waybill ID does not match.')
        if fields.get('BUYER_TIN') != self.config.buyer_tin: raise ValidationError('This waybill is not addressed to the configured company TIN.')
        if fields.get('STATUS') not in {'1', '2'}: raise ValidationError('Only activated or completed incoming waybills can be received.')
        goods_list = next((node for node in root if local(node.tag) == 'GOODS_LIST'), None)
        goods, seen = [], set()
        for node in goods_list if goods_list is not None else []:
            if local(node.tag) != 'GOODS': continue
            row = children(node)
            if row.get('STATUS') == '-1': continue
            if row.get('STATUS') not in {None, '', '1'}: raise ValidationError('A goods line has an unfamiliar status. Review it in RS.ge.')
            if not row.get('ID') or row['ID'] in seen: raise ValidationError('Waybill goods need unique line IDs.')
            seen.add(row['ID']); goods.append(row)
        if not goods or len(goods) > 500: raise ValidationError('Receive waybills with 1–500 goods lines.')
        source = XML.tostring(root, encoding='unicode')
        return source, {'fields': fields, 'goods': goods}


def stage(config, identifier):
    client = RSClient(config)
    source, data = client.detail(identifier)
    digest = hashlib.sha256(source.encode()).hexdigest()
    with transaction.atomic():
        Installation.objects.select_for_update().get(pk=1)
        item = ReceivedWaybill.objects.filter(company=config.company, external_id=str(identifier)).first()
        if item and item.received_at:
            if item.source_hash != digest: raise ValidationError('This received waybill changed in RS.ge. Review the original receipt and post an audited stock correction; it will not be received twice.')
            return item
        item = item or ReceivedWaybill(company=config.company, external_id=str(identifier))
        units = client.call('get_waybill_units')
        names = {children(node).get('ID'): children(node).get('NAME', '') for node in units if local(node.tag) == 'WAYBILL_UNIT'}
        for row in data['goods']:
            row['DISPLAY_UNIT'] = row.get('UNIT_TXT') or names.get(row.get('UNIT_ID')) or ('RS unit ' + row.get('UNIT_ID', '?'))
        item.number = data['fields'].get('WAYBILL_NUMBER', '')[:100]
        item.source_xml, item.source_hash, item.source_data, item.service_user = source, digest, data, config.service_user
        item.save()
        return item


def quantity_milli(value, unit):
    try: quantity = Decimal(value)
    except (InvalidOperation, TypeError): raise ValidationError('Enter a valid received quantity.')
    if not quantity.is_finite() or quantity <= 0 or quantity > 1000000 or quantity * 1000 != (quantity * 1000).to_integral_value():
        raise ValidationError('Quantity must be positive, at most 1,000,000, with at most three decimal places.')
    if unit == 'piece' and quantity != quantity.to_integral_value(): raise ValidationError('Piece quantities must be whole numbers.')
    return int(quantity * 1000)


@transaction.atomic
def receive(item, location, mappings, actor, expected_hash):
    Installation.objects.select_for_update().get(pk=1)
    item = ReceivedWaybill.objects.select_for_update().get(pk=item.pk)
    if item.received_at: raise ValidationError('This waybill has already been received. Stock was not changed.')
    if item.source_hash != expected_hash: raise ValidationError('The waybill changed. Reload and review it again.')
    if location.company_id != item.company_id or not location.active: raise ValidationError('Choose an active receiving location in this company.')
    if len(mappings) != len(item.source_data['goods']): raise ValidationError('Map every goods line.')
    prepared = []
    for source, mapping in zip(item.source_data['goods'], mappings):
        product = Product.objects.get(pk=mapping['product'], company=item.company, active=True)
        amount = quantity_milli(mapping['quantity'], product.unit)
        # The operator explicitly confirms unit conversion and any discrepancy in the review form.
        reason = mapping.get('reason', '').strip()
        try: source_quantity = Decimal(source.get('QUANTITY', ''))
        except InvalidOperation: raise ValidationError('RS.ge returned an invalid source quantity.')
        if not source_quantity.is_finite() or source_quantity <= 0: raise ValidationError('RS.ge returned a nonpositive source quantity.')
        if Decimal(amount) / 1000 != source_quantity and len(reason) < 3: raise ValidationError('Explain every quantity difference or unit conversion.')
        if len(reason) > 250: raise ValidationError('Keep a receiving note within 250 characters.')
        prepared.append({'line_id': source['ID'], 'product': str(product.pk), 'name': product.name, 'unit': product.unit,
                         'quantity_milli': amount, 'reason': reason})
    # Stable product ordering avoids deadlocks when two receipts touch overlapping inventory.
    for row in sorted(prepared, key=lambda value: value['product']):
        stock, _ = StockItem.objects.get_or_create(product_id=row['product'], location=location)
        StockItem.objects.select_for_update().get(pk=stock.pk)
        StockItem.objects.filter(pk=stock.pk).update(quantity_milli=F('quantity_milli') + row['quantity_milli'])
        StockMovement.objects.create(stock_item=stock, quantity_milli=row['quantity_milli'], reason='rs_waybill',
            note=f"RS.ge {item.external_id}, line {row['line_id']}. {row['reason']}"[:250], actor=actor)
    item.location, item.received_by, item.received_at, item.receipt_lines = location, actor, timezone.now(), prepared
    item.save()
    return item
