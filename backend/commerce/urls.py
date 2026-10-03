from django.urls import path
from . import views, cashier_views, supervision
from .enrollment import enrollment
from . import advertisements, updates
urlpatterns = [path("advertisements/<uuid:identifier>/<str:digest>/", advertisements.image), path("cashier/updates/", updates.update_poll), path("catalog/", views.catalog), path("sales/", views.sales),
    path("cashier/sign-in/", cashier_views.sign_in), path("cashier/sign-out/", cashier_views.sign_out),
    path("basket/sync/", supervision.basket_sync), path("cashier/enrollment/", enrollment)]
