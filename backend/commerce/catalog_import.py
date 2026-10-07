"""Bounded catalog imports. Stock is never created or changed by this module."""
import csv
import io
import zipfile
from decimal import Decimal, InvalidOperation
from pathlib import Path

from defusedxml import ElementTree
from django.core.exceptions import ValidationError
from django.db import transaction
from .models import Category, Installation, Product

HEADERS = {
    'products': ['barcode', 'name', 'name_ka', 'category', 'subcategory', 'unit', 'price', 'active'],
    'categories': ['name', 'name_ka', 'parent'],
}
EXAMPLES = {
    'categories': [['Drinks', 'სასმელები', ''], ['Alcohol', 'ალკოჰოლი', 'Drinks']],
    'products': [['EX-000001', 'OLMECA Tequila', '', 'Drinks', 'Alcohol', 'piece', '65.00', 'true'],
                 ['EX-000042', 'House lemonade', '', 'Drinks', '', 'liter', '4.50', 'true']],
}
SINGULAR = {'products': 'product', 'categories': 'category'}
MAX_BYTES, MAX_ROWS = 10 * 1024 * 1024, 5000


def parse_upload(upload, kind):
    if kind not in HEADERS: raise ValidationError('Unknown catalog type.')
    if upload.size > MAX_BYTES: raise ValidationError('Choose a file up to 10 MB.')
    raw = upload.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES: raise ValidationError('Choose a file up to 10 MB.')
    suffix = Path(upload.name).suffix.lower()
    try:
        if suffix == '.csv':
            table = []
            for row in csv.reader(io.StringIO(raw.decode('utf-8-sig')), strict=True):
                if len(table) >= MAX_ROWS + 1 or len(row) > 30: raise ValidationError('Use at most 5,000 rows and 30 columns.')
                table.append(row)
        elif suffix == '.xlsx':
            import openpyxl
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                if len(archive.infolist()) > 2000 or sum(i.file_size for i in archive.infolist()) > 40 * 1024 * 1024:
                    raise ValidationError('Excel file expands beyond the supported size.')
            workbook = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=False, keep_links=False)
            try:
                sheet = workbook.worksheets[0]
                if sheet.max_row and sheet.max_row > MAX_ROWS + 1 or sheet.max_column and sheet.max_column > 30:
                    raise ValidationError('Use at most 5,000 rows and 30 columns.')
                table = []
                for row in sheet.iter_rows():
                    if any(cell.data_type == 'f' for cell in row): raise ValidationError('Replace Excel formulas with values before importing.')
                    table.append([cell.value for cell in row])
                    if len(table) > MAX_ROWS + 1: raise ValidationError('Use at most 5,000 rows.')
            finally: workbook.close()
        elif suffix == '.xls':
            import xlrd
            workbook = xlrd.open_workbook(file_contents=raw, on_demand=True)
            try:
                sheet = workbook.sheet_by_index(0)
                if sheet.nrows > MAX_ROWS + 1 or sheet.ncols > 30: raise ValidationError('Use at most 5,000 rows and 30 columns.')
                table = [sheet.row_values(i) for i in range(sheet.nrows)]
            finally: workbook.release_resources()
        elif suffix == '.xml':
            root = ElementTree.fromstring(raw, forbid_dtd=True, forbid_entities=True, forbid_external=True)
            if root.tag != kind: raise ValidationError(f'The XML root must be <{kind}>.')
            table = [HEADERS[kind]]
            for item in root:
                if item.tag != SINGULAR[kind] or item.attrib or any(len(cell) or cell.attrib for cell in item):
                    raise ValidationError('Use the flat XML structure in the example.')
                fields = [cell.tag for cell in item]
                if len(set(fields)) != len(fields) or set(fields) - set(HEADERS[kind]): raise ValidationError('XML contains duplicate or unknown fields.')
                table.append([item.findtext(field, '') for field in HEADERS[kind]])
                if len(table) > MAX_ROWS + 1: raise ValidationError('Use at most 5,000 rows.')
        else: raise ValidationError('Choose CSV, XLS, XLSX or XML.')
    except ValidationError: raise
    except Exception as error:
        raise ValidationError('The file could not be read. Use UTF-8 CSV or one of the supplied examples.') from error
    if len(table) < 2 or len(table) > MAX_ROWS + 1: raise ValidationError('Include a header and between 1 and 5,000 data rows.')
    header = [str(v or '').strip().lower() for v in table[0]]
    while header and not header[-1]: header.pop()
    if len(set(header)) != len(header) or set(header) != set(HEADERS[kind]):
        raise ValidationError('Use exactly these column names: ' + ', '.join(HEADERS[kind]))
    rows = []
    for number, values in enumerate(table[1:], 2):
        if not any(v is not None and str(v).strip() for v in values): continue
        if any(v is not None and str(v).strip() for v in values[len(header):]): raise ValidationError(f'Row {number}: too many columns.')
        values = list(values) + [''] * (len(header) - len(values))
        row = {}
        for key, value in zip(header, values):
            if key == 'barcode' and isinstance(value, (float, int)):
                raise ValidationError(f'Row {number}: format the barcode as Text in Excel to preserve leading zeros.')
            row[key] = '' if value is None else str(value).strip()
            if len(row[key]) > 1000: raise ValidationError(f'Row {number}: {key} is too long.')
        row['_row'] = number
        rows.append(row)
    if not rows: raise ValidationError('The file has no data rows.')
    return rows


def category_named(company, name, parent=None):
    found = list(Category.objects.filter(company=company, parent=parent, name__iexact=name)[:2])
    if len(found) != 1:
        raise ValidationError(f'Category "{name}" is missing or ambiguous. Import categories first, or resolve duplicate names.')
    return found[0]


@transaction.atomic
def apply_import(company, kind, rows, *, preview=False):
    # Serialize concurrent imports and receiving operations on all supported databases.
    Installation.objects.select_for_update().get(pk=1)
    created = updated = 0
    errors, seen = [], set()
    ordered = sorted(rows, key=lambda r: bool(r.get('parent'))) if kind == 'categories' else rows
    for row in ordered:
        try:
            with transaction.atomic():
                if kind == 'categories':
                    parent = category_named(company, row['parent']) if row['parent'] else None
                    key = (row['parent'].casefold(), row['name'].casefold())
                    if key in seen: raise ValidationError('Duplicate category in this file.')
                    seen.add(key)
                    existing = list(Category.objects.filter(company=company, parent=parent, name__iexact=row['name'])[:2])
                    if len(existing) > 1: raise ValidationError('Multiple existing categories have this name. Resolve them first.')
                    item = existing[0] if existing else Category(company=company, parent=parent)
                    item.name, item.name_ka = row['name'], row['name_ka']
                else:
                    if row['barcode'] in seen: raise ValidationError('Duplicate barcode in this file.')
                    seen.add(row['barcode'])
                    item = Product.objects.filter(company=company, barcode=row['barcode']).first() or Product(company=company)
                    category = category_named(company, row['category']) if row['category'] else None
                    if row['subcategory'] and not category: raise ValidationError('A subcategory requires a category.')
                    item.category = category
                    item.subcategory = category_named(company, row['subcategory'], category) if row['subcategory'] else None
                    for field in ('barcode', 'name', 'name_ka', 'unit'): setattr(item, field, row[field])
                    try: price = Decimal(row['price'])
                    except InvalidOperation: raise ValidationError('Price must be a decimal amount in GEL.')
                    if not price.is_finite() or price < 0 or price > 1000000 or price * 100 != (price * 100).to_integral_value():
                        raise ValidationError('Price must be 0–1,000,000 GEL with at most two decimal places.')
                    item.price_minor = int(price * 100)
                    if row['active'].lower() not in {'true', 'false', '1', '0', '1.0', '0.0'}: raise ValidationError('Active must be true or false.')
                    item.active = row['active'].lower() in {'true', '1', '1.0'}
                new = item._state.adding
                item.full_clean()
                item.save()
                created += int(new)
                updated += int(not new)
        except ValidationError as error:
            errors.append(f"Row {row['_row']}: {'; '.join(error.messages)}")
            if len(errors) >= 50: break
    if errors: raise ValidationError(errors)
    if preview: transaction.set_rollback(True)
    return {'created': created, 'updated': updated, 'count': len(rows)}
