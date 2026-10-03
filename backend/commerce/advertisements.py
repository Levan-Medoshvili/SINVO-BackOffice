from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view
from .models import Advertisement


def for_branch(branch):
    now = timezone.now()
    return Advertisement.objects.filter(company=branch.company, active=True).filter(Q(all_branches=True)|Q(branches=branch)).filter(Q(starts_at__isnull=True)|Q(starts_at__lte=now)).filter(Q(ends_at__isnull=True)|Q(ends_at__gt=now)).distinct().order_by('position','title','id')


def playlist(branch):
    return [{'id':str(a.pk), 'title':a.title, 'text':a.text, 'duration_seconds':a.duration_seconds,
        'ends_at':a.ends_at.isoformat() if a.ends_at else None,
        'image':{'url':f'/api/v1/advertisements/{a.pk}/{a.image_sha256}/', 'sha256':a.image_sha256} if a.image else None}
        for a in for_branch(branch)[:10]]


@api_view(['GET'])
def image(request, identifier, digest):
    ad = get_object_or_404(for_branch(request.auth.location), pk=identifier, image_sha256=digest)
    if not ad.image: raise Http404()
    response = FileResponse(ad.image.open('rb'), content_type='image/webp')
    response['Cache-Control']='private, max-age=300'
    response['X-Content-Type-Options']='nosniff'
    return response
