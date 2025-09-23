from django.contrib import admin
from django.urls import path,include
from . import views
from django.views.decorators.cache import cache_page

from . import analytics

# Create an instance of the admin class to access its methods

# from LaundryApp.admin import dashboard_view  # Import your new view
app_name = "laundry"
urlpatterns = [
    path('djadmin', admin.site.urls),
    path('home',views.home, name='home'),
    path('sd',views.Reportsdashboard,name='dashboardg'),
    path('accounts/', include('django_registration.backends.activation.urls')),
    path('accounts/', include('django.contrib.auth.urls')),
    path('logout',views.logout_view, name='logout'),
    path('mpesa/initiate-payment/<int:order_id>/', views.initiatepayment, name='Mpesa_payment_initiation'),
    path('daraja/stk_push',views.stk_push_callback, name='stk_push_callback'),
    path('mpesa/callback/', views.stk_push_callback, name='mpesa_callback'),
    path('Report/', cache_page(60 * 5)(views.dashboard_view), 
         name='laundryapp_dashboard'),
    
    path('Laundry-dashboard', views.laundrydashboard, name='Laundrydashboard'),
    path('', views.get_laundry_profit_and_hotel, name='dashboard'),

    path('search-customers/', views.search_customers, name='search_customers'),
    path('createorder/', views.createorder, name='createorder'),

    path('Tables/', views.customordertable, name='customordertable'),
    path('order/<str:order_code>/status/<str:status>/', views.update_order_status, name='update_order_status'),
    path('order/<str:order_code>/', views.order_detail, name='order_detail'),
    path('order/<str:order_code>/edit/', views.order_edit, name='order_edit'),
    path('order/<str:order_code>/delete/', views.order_delete, name='order_delete'),
    #path('order/<str:order_code>/complete/', views.mark_order_completed, name='mark_order_completed'),
    path('order/<str:order_code>/update-payment/', views.update_payment_status, name='update_payment_status'),
    
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
   
    path('expense-fields/create/', views.create_expense_field, name='create_expense_field'),
    path('expense-fields/', views.expense_field_list, name='expense_field_list'),
    path('expense-fields/edit/<int:field_id>/', views.edit_expense_field, name='edit_expense_field'),
    path('expense-fields/delete/<int:field_id>/', views.delete_expense_field, name='delete_expense_field'),
    path('expenses/create/', views.expense_form, name='expense_form'),
    path('expenses/', views.expense_list, name='expense_list'),
    path('expenses/edit/<int:record_id>/', views.edit_expense_record, name='edit_expense_record'),
    path('expenses/delete/<int:record_id>/', views.delete_expense_record, name='delete_expense_record'),
   
    path('debug/shop-values/', views.debug_shop_values, name='debug_shop_values'),
    path("debug-users/", views.debug_users, name="debug_users"),

    
]