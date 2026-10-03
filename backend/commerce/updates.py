"""Signed, immutable release storage and register-scoped update delivery."""
import base64
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import CashierRelease, CashierDeviceStatus, UpdateDelivery, Installation

VERSION = r'(0|[1-9]\d{0,8})\.(0|[1-9]\d{0,8})\.(0|[1-9]\d{0,8})'

def version_tuple(value):
    if not isinstance(value,str) or not re.fullmatch(VERSION,value): raise ValueError('Invalid version.')
    return tuple(map(int,value.split('.')))


def import_release(manifest_file, signature_file, archive, actor, *, allow_existing=False):
    key = settings.SIMPLEPOS_RELEASE_PUBLIC_KEY
    if not key.is_file(): raise ValidationError('Install the trusted release public key on the server before importing releases. See the update setup instructions.')
    if manifest_file.size > 65536 or signature_file.size > 4096 or archive.size > 1073741824: raise ValidationError('Release files exceed their size limits.')
    raw = manifest_file.read()
    try:
        m = json.loads(raw); version_tuple(m['version'])
        if m['schema'] != 1 or m['platform'] not in {'win-x64','linux-x64'}: raise ValueError()
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,150}',m['filename']): raise ValueError()
        if not m['filename'].endswith('.zip' if m['platform']=='win-x64' else '.AppImage'): raise ValueError()
        if type(m['size']) is not int or not 1 <= m['size'] <= 1073741824 or m['size'] != archive.size: raise ValueError()
        if not re.fullmatch(r'[a-f0-9]{64}',m['sha256']): raise ValueError()
        signature = base64.b64decode(signature_file.read().strip(),validate=True)
    except (ValueError,KeyError,TypeError): raise ValidationError('Invalid signed release metadata or package size.') from None
    root = settings.SIMPLEPOS_RELEASE_DIR / m['platform'] / 'versions'
    root.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.import-',dir=root) as temp:
        stage = Path(temp)
        (stage/'manifest.json').write_bytes(raw); (stage/'signature.bin').write_bytes(signature)
        try:
            verified = subprocess.run(['openssl','dgst','-sha256','-verify',str(key),'-signature',str(stage/'signature.bin'),str(stage/'manifest.json')],capture_output=True,timeout=15)
        except (OSError,subprocess.TimeoutExpired): raise ValidationError('The server could not verify the release signature.') from None
        if verified.returncode: raise ValidationError('The release signature does not match the trusted public key.')
        (stage/'signature.bin').unlink(); (stage/'manifest.sig').write_bytes(base64.b64encode(signature)+b'\n')
        digest=hashlib.sha256()
        with (stage/m['filename']).open('wb') as output:
            for chunk in archive.chunks(): digest.update(chunk); output.write(chunk)
        if digest.hexdigest()!=m['sha256']: raise ValidationError('Package checksum does not match the signed manifest.')
        with transaction.atomic():
            Installation.objects.select_for_update().get(pk=1)
            existing_release = CashierRelease.objects.filter(platform=m['platform'],version=m['version']).first()
            if existing_release:
                if not allow_existing: raise ValidationError('This release version is already imported.')
                if any(getattr(existing_release, field) != m[field] for field in ('filename', 'size', 'sha256')):
                    raise ValidationError('A different package already uses this version. Publish a new version.')
            destination=root/m['version']
            if existing_release and not destination.is_dir():
                raise ValidationError('Existing version files are missing. Restore the original signed release files.')
            if destination.exists():
                if (destination/'manifest.json').read_bytes()!=raw: raise ValidationError('A different package already uses this version. Publish a new version.')
                if (destination/'manifest.sig').read_bytes().strip() != base64.b64encode(signature):
                    raise ValidationError('Existing release signature is damaged. Restore the original signed release files.')
                existing=hashlib.sha256()
                with (destination/m['filename']).open('rb') as source:
                    for chunk in iter(lambda:source.read(1024*1024),b''): existing.update(chunk)
                if existing.hexdigest()!=m['sha256']: raise ValidationError('Existing version files are damaged. Publish a new version.')
            else: os.rename(stage,destination)
            if existing_release: return existing_release
            return CashierRelease.objects.create(version=m['version'],platform=m['platform'],filename=m['filename'],size=m['size'],sha256=m['sha256'],uploaded_by=actor)


@api_view(['POST'])
def update_poll(request):
    data=request.data
    if not isinstance(data,dict): return Response({'detail':'Invalid update report.'},status=400)
    try:
        version_tuple(data['version'])
        if data['platform'] not in {'win-x64','linux-x64'} or type(data.get('updater_ready')) is not bool: raise ValueError()
    except (ValueError,KeyError,TypeError): return Response({'detail':'Invalid update report.'},status=400)
    register=request.auth
    with transaction.atomic():
        type(register).objects.select_for_update().get(pk=register.pk)
        CashierDeviceStatus.objects.update_or_create(register=register,defaults={'version':data['version'],'platform':data['platform'],'updater_ready':data['updater_ready']})
        delivery=UpdateDelivery.objects.select_related('rollout__release').filter(register=register,
            rollout__starts_at__lte=timezone.now(),rollout__release__platform=data['platform']).order_by('-rollout__created_at').first()
        if not delivery or delivery.rollout.cancelled_at: return Response({'update':None})
        release=delivery.rollout.release
        delivery.reported_version=data['version']; delivery.reported_at=timezone.now()
        installed=version_tuple(data['version'])>=version_tuple(release.version)
        if installed: delivery.status='installed'; delivery.detail='POS reports this version or newer.'
        elif not data['updater_ready']: delivery.status='error'; delivery.detail='Run the trusted v0.4+ starter once to enable managed updates.'
        elif str(delivery.pk)==str(data.get('delivery_id')) and data.get('status') in {'waiting','installing','error'}:
            delivery.status=data['status']; delivery.detail=str(data.get('detail',''))[:250]
        elif delivery.status not in {'installing','error'}: delivery.status='waiting'; delivery.detail='Update offered; waiting for an idle checkout.'
        delivery.save(update_fields=['reported_version','reported_at','status','detail'])
        UpdateDelivery.objects.filter(register=register,rollout__release__platform=data['platform'],rollout__created_at__lt=delivery.rollout.created_at).exclude(status__in=['installed','superseded']).update(status='superseded')
    return Response({'update':None if installed else {'id':str(delivery.pk),'version':release.version,'platform':release.platform}})
