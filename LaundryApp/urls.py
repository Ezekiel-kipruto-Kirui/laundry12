from django.contrib import admin
from django.urls import path,include
from . import views
# from LaundryApp.admin import dashboard_view  # Import your new view

urlpatterns = [
    path('', admin.site.urls),
    path('home',views.home, name='home'),
    path('accounts/', include('django_registration.backends.activation.urls')),
    path('accounts/', include('django.contrib.auth.urls')),
    path('order/', views.laundry_form, name='laundry_form'),
    path('order/success/', views.laundry_form_success, name='laundry_form_success'),
    path('api/customer-details/', views.get_customer_details, name='get_customer_details'),
    path('',views.index, name='index'),
    path('daraja/stk_push',views.stk_push_callback, name='stk_push_callback'),
    path('mpesa/callback/', views.stk_push_callback, name='mpesa_callback'),

]