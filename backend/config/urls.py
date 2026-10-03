from django.urls import path, include
from django.conf.urls.static import static
from django.conf import settings
from django.views.generic import RedirectView
from commerce.views import health
from commerce.releases import release_file

urlpatterns = [
    path('admin/', RedirectView.as_view(url='/', permanent=False)),
    path('admin/login/', RedirectView.as_view(url='/login/', permanent=False)),
    path('i18n/', include('django.conf.urls.i18n')),
    path('healthz/', health),
    path("cashier/releases/<str:platform>/<str:filename>", release_file),
    path('api/v1/', include('commerce.urls')),
]

urlpatterns += [path('', include('backoffice.urls'))]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
