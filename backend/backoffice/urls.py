from django.urls import path
from . import views

app_name = 'backoffice'
urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('setup/', views.setup, name='setup'),
    path('login/', views.sign_in, name='login'),
    path('logout/', views.sign_out, name='logout'),
    path('company/', views.company_settings, name='company'),
    path('password/', views.password, name='password'),
    path('team/', views.users, name='users'),
    path('team/add/', views.user_edit, name='user-add'),
    path('team/<uuid:identifier>/', views.user_edit, name='user-edit'),
    path('sales/', views.sales, name='sales'),
    path('sales/<uuid:identifier>/', views.sale, name='sale'),
    path('checkouts/', views.checkouts, name='checkouts'),
    path('checkouts/<uuid:identifier>/', views.checkout, name='checkout'),
    path('enrollment/<uuid:identifier>/', views.review, name='review'),
    path('branches/<uuid:identifier>/pair/', views.pair, name='pair'),
    path('inventory/<uuid:identifier>/adjust/', views.adjust, name='adjust'),
    path('manage/<str:section>/', views.listing, name='list'),
    path('manage/<str:section>/add/', views.edit, name='add'),
    path('manage/<str:section>/<uuid:identifier>/', views.edit, name='edit'),
    path('manage/<str:section>/<uuid:identifier>/delete/', views.delete, name='delete'),
]
