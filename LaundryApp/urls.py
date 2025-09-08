from django.contrib import admin
from django.urls import path,include
from . import views
# from LaundryApp.admin import dashboard_view  # Import your new view

urlpatterns = [
    path('', admin.site.urls),
    path('home',views.home, name='home'),
    path('accounts/', include('django_registration.backends.activation.urls')),
    path('accounts/', include('django.contrib.auth.urls')),
    path('Mpesa',views.index, name='index'),
    path('daraja/stk_push',views.stk_push_callback, name='stk_push_callback'),
    path('mpesa/callback/', views.stk_push_callback, name='mpesa_callback'),
    
]