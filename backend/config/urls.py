from django.contrib import admin
from django.urls import path, include
from django.conf.urls.static import static
from django.conf import settings
from django.views.generic import RedirectView
from commerce.views import health
from commerce.releases import release_file

urlpatterns = [
    path('admin/', admin.site.urls),
    path('i18n/', include('django.conf.urls.i18n')),
    path('healthz/', health),
    path("cashier/releases/<str:platform>/<str:filename>", release_file),
    path('api/v1/', include('commerce.urls')),
]

urlpatterns += [path('', RedirectView.as_view(url='/admin/', permanent=False), name='index')]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
