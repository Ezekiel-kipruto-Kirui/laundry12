from django.contrib import admin
from django.urls import path,include
from . import views
from django.views.decorators.cache import cache_page

# Create an instance of the admin class to access its methods

# from LaundryApp.admin import dashboard_view  # Import your new view

urlpatterns = [
    path('djadmin', admin.site.urls),
    path('home',views.home, name='home'),
    path('sd',views.dashboard,name='dashboardg'),
    path('accounts/', include('django_registration.backends.activation.urls')),
    path('accounts/', include('django.contrib.auth.urls')),
    path('logout',views.logout_view, name='logout'),
    path('Mpesa',views.index, name='index'),
    path('daraja/stk_push',views.stk_push_callback, name='stk_push_callback'),
    path('mpesa/callback/', views.stk_push_callback, name='mpesa_callback'),
    path('Report/', cache_page(60 * 5)(views.dashboard_view), 
         name='laundryapp_dashboard'),
    
    path('', views.generaldashboard, name='dashboard'),

    
    path('Tables/', views.customordertable, name='customordertable'),
    
    path('createorder/', views.createorder, name='createorder'),
    
    path('create-order-api/', views.create_order_api, name='create_order_api'),
    
    path('check-customer/', views.check_customer, name='check_customer'),
    
     path('user-management/', views.user_management, name='user_management'),
    path('user/add/', views.user_add, name='user_add'),
    path('user/<int:pk>/edit/', views.user_edit, name='user_edit'),
    path('user/<int:pk>/delete/', views.user_delete, name='user_delete'),
    path('user/<int:pk>/profile/', views.user_profile, name='user_profile'),
    
    # Customer Management URLs
    path('customer-management/', views.customer_management, name='customer_management'),
    path('customer/add/', views.customer_add, name='customer_add'),
    path('customer/<int:pk>/edit/', views.customer_edit, name='customer_edit'),
    path('customer/<int:pk>/delete/', views.customer_delete, name='customer_delete'),
    path('customer/<int:pk>/orders/', views.customer_orders, name='customer_orders'),
   

    
]