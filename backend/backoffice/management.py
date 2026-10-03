from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.conf import settings
from commerce.models import Advertisement, CashierRelease, UpdateRollout, UpdateDelivery, Register, Location, Installation
from commerce.updates import import_release
from .access import backoffice
from .forms import AdvertisementForm, ReleaseImportForm, RolloutForm

@backoffice('manage_advertisements')
def advertisements(request):
    return render(request,'backoffice/advertisements.html',{'nav':'advertisements','ads':Advertisement.objects.filter(company=request.company).prefetch_related('branches').order_by('position','title')})

@backoffice('manage_advertisements')
def advertisement_edit(request,identifier=None):
    item=get_object_or_404(Advertisement,pk=identifier,company=request.company) if identifier else None
    form=AdvertisementForm(request.POST or None,request.FILES or None,instance=item,company=request.company)
    if request.method=='POST' and form.is_valid():
        form.save(); messages.success(request,'Advertisement saved. Connected cashiers refresh within one minute.')
        return redirect('backoffice:advertisements')
    return render(request,'backoffice/form.html',{'nav':'advertisements','title':'Edit advertisement' if item else 'Add advertisement','form':form,'back_url':'backoffice:advertisements'})

@backoffice('manage_advertisements')
def advertisement_preview(request,identifier):
    item=get_object_or_404(Advertisement,pk=identifier,company=request.company)
    if not item.image: raise Http404()
    return FileResponse(item.image.open('rb'),content_type='image/webp')

@backoffice('manage_updates')
def updates(request):
    form=RolloutForm(request.POST or None,company=request.company)
    if request.method=='POST' and form.is_valid():
        data=form.cleaned_data
        branches=Location.objects.filter(company=request.company,kind='branch',active=True) if data['all_branches'] else data['branches']
        registers=Register.objects.filter(location__in=branches,active=True).filter(Q(cashierdevicestatus__isnull=True)|Q(cashierdevicestatus__platform=data['release'].platform))
        with transaction.atomic():
            Installation.objects.select_for_update().get(pk=1)
            targets=list(registers)
            if not targets: form.add_error(None,'No active POS terminals match these branches and the selected platform.')
            else:
                rollout=UpdateRollout.objects.create(company=request.company,release=data['release'],created_by=request.user,all_branches=data['all_branches'],starts_at=data['starts_at'] or timezone.now())
                rollout.branches.set(branches)
                UpdateDelivery.objects.bulk_create([UpdateDelivery(rollout=rollout,register=r) for r in targets])
                messages.success(request,f'Update queued for {len(targets)} POS terminals. Offline terminals receive it when they reconnect.')
                return redirect('backoffice:rollout',identifier=rollout.pk)
    history=UpdateRollout.objects.filter(company=request.company).select_related('release','created_by').order_by('-created_at')
    devices=Register.objects.filter(location__company=request.company).select_related('location','cashierdevicestatus').order_by('location__name','name')
    return render(request,'backoffice/updates.html',{'nav':'updates','form':form,'rollouts':history[:30],'devices':devices,'key_ready':settings.SIMPLEPOS_RELEASE_PUBLIC_KEY.is_file(),'release_count':CashierRelease.objects.count()})

@backoffice('manage_updates')
def release_import(request):
    form=ReleaseImportForm(request.POST or None,request.FILES or None)
    if request.method=='POST' and form.is_valid():
        try: import_release(form.cleaned_data['manifest'],form.cleaned_data['signature'],form.cleaned_data['archive'],request.user)
        except (ValidationError,OSError) as error:
            form.add_error(None,'; '.join(error.messages) if isinstance(error,ValidationError) else 'Release storage is unavailable. Check server storage and permissions.')
        else:
            messages.success(request,'Signed release verified and imported. Choose its target branches to push it.')
            return redirect('backoffice:updates')
    return render(request,'backoffice/form.html',{'nav':'updates','title':'Import signed Cashier release','subtitle':'Upload the manifest, signature and package produced by the trusted release signing tool.','form':form,'back_url':'backoffice:updates'})

@backoffice('manage_updates')
def rollout(request,identifier):
    item=get_object_or_404(UpdateRollout.objects.select_related('release','created_by'),pk=identifier,company=request.company)
    page=Paginator(item.deliveries.select_related('register__location').order_by('register__location__name','register__name'),50).get_page(request.GET.get('page'))
    return render(request,'backoffice/rollout.html',{'nav':'updates','rollout':item,'page':page})

@require_POST
@backoffice('manage_updates')
def cancel_rollout(request,identifier):
    item=get_object_or_404(UpdateRollout,pk=identifier,company=request.company)
    item.cancelled_at=timezone.now(); item.save(update_fields=['cancelled_at'])
    messages.success(request,'Rollout cancelled. A POS that has already started installing may finish.')
    return redirect('backoffice:rollout',identifier=item.pk)
