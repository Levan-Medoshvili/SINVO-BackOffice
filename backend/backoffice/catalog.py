import base64
import csv
import io
import secrets
from pathlib import Path
from xml.etree import ElementTree
from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from commerce.catalog_import import HEADERS, EXAMPLES, SINGULAR, parse_upload, apply_import
from .access import backoffice


class ImportForm(forms.Form):
    file = forms.FileField(label='Import file', widget=forms.ClearableFileInput(attrs={'accept': '.csv,.xls,.xlsx,.xml'}))


@backoffice('manage_catalog')
def catalog_import(request, kind):
    if kind not in HEADERS: raise Http404()
    form = ImportForm(request.POST or None, request.FILES or None)
    key = 'catalog_import_' + kind
    context = {'nav': kind, 'kind': kind, 'form': form, 'headers': HEADERS[kind]}
    if request.method == 'POST':
        try:
            if request.POST.get('confirm'):
                pending = request.session.get(key)
                if not pending or not secrets.compare_digest(pending['token'], request.POST['confirm']) or pending['company'] != str(request.company.pk):
                    raise ValidationError('This preview has expired. Upload the file again.')
                result = apply_import(request.company, kind, pending['rows'])
                del request.session[key]
                messages.success(request, f"Imported {result['count']} {kind}: {result['created']} added, {result['updated']} updated.")
                return redirect('backoffice:list', section=kind)
            elif form.is_valid():
                rows = parse_upload(form.cleaned_data['file'], kind)
                result = apply_import(request.company, kind, rows, preview=True)
                token = secrets.token_urlsafe(24)
                request.session[key] = {'token': token, 'company': str(request.company.pk), 'rows': rows}
                context.update(preview=[[r[h] for h in HEADERS[kind]] for r in rows[:25]], result=result, token=token)
        except (ValidationError, IntegrityError) as error:
            form.add_error(None, error if isinstance(error, ValidationError) else 'The catalog changed during import. Upload the file again.')
    return render(request, 'backoffice/import.html', context)


@backoffice('manage_catalog')
def example(request, kind, extension):
    if kind not in HEADERS or extension not in {'csv', 'xlsx', 'xml'}: raise Http404()
    if extension == 'xlsx':
        data = base64.b64decode((Path(__file__).parent / 'examples' / f'{kind}.xlsx.base64').read_bytes())
        mime = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    elif extension == 'csv':
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(HEADERS[kind])
        writer.writerows(EXAMPLES[kind])
        data, mime = ('\ufeff' + output.getvalue()).encode(), 'text/csv; charset=utf-8'
    else:
        root = ElementTree.Element(kind)
        for row in EXAMPLES[kind]:
            item = ElementTree.SubElement(root, SINGULAR[kind])
            for field, value in zip(HEADERS[kind], row): ElementTree.SubElement(item, field).text = str(value)
        ElementTree.indent(root)
        data, mime = ElementTree.tostring(root, encoding='utf-8', xml_declaration=True), 'application/xml'
    response = HttpResponse(data, content_type=mime)
    response['Content-Disposition'] = f'attachment; filename="{kind}-example.{extension}"'
    return response
