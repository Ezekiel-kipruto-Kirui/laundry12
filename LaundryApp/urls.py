from django.contrib import admin
from django.urls import path, include
from . import views
from .businesses import *
from LaundryApp.View import Expenses, customers, usermanage
from django.views.decorators.cache import cache_page
from django.contrib.auth import views as auth_views

app_name = "laundry"

urlpatterns = [
    # Django Admin
    path('djadmin', admin.site.urls),
    
    # Authentication & Accounts
    path('accounts/', include('django_registration.backends.activation.urls')),
    path('accounts/', include('django.contrib.auth.urls')),
    path('logout', views.logout_view, name='logout'),
    
    # Password Reset URLs
    path('password_reset/', 
         auth_views.PasswordResetView.as_view(template_name="registration/password_reset.html"), 
         name='password_reset'),
    path('password_reset/done/', 
         auth_views.PasswordResetDoneView.as_view(template_name="registration/password_reset_done.html"), 
         name='password_reset_done'),
    path('reset/<uidb64>/<token>/', 
         auth_views.PasswordResetConfirmView.as_view(template_name="registration/password_reset_confirm.html"), 
         name='password_reset_confirm'),
    path('reset/done/', 
         auth_views.PasswordResetCompleteView.as_view(template_name="registration/password_reset_complete.html"), 
         name='password_reset_complete'),
    
    # Dashboard & Reports
    path('', views.get_laundry_profit_and_hotel, name='dashboard'),
    path('Laundry-dashboard', views.laundrydashboard, name='Laundrydashboard'),
    path('Report/', cache_page(60 * 5)(views.dashboard_view), name='laundryapp_dashboard'),
    path('dbw', dashboard_home, name='dashboard_home'),
    path('api/dashboard-data/', get_dashboard_data, name='dashboard_data'),
    
    # Order Management
    path('createorder/', views.createorder, name='createorder'),
    path('Tables/', views.customordertable, name='customordertable'),
    path('get-order-details/<int:order_id>/', views.order_detail, name='get_order_details'),  # FIXED: Removed trailing slash
    path('update-order/', views.order_edit, name='update_order_ajax'),
    path('order-delete/<str:order_code>/', views.order_delete, name='order_delete'),
    # Order Actions
    path('order/<str:order_code>/status/<str:status>/', views.update_order_status_ajax, name='update_order_status'),
    #path('order/<str:order_code>/delete/', views.order_delete, name='order_delete'),
    path('order/<str:order_code>/update-payment/', views.update_payment_status, name='update_payment_status'),
    path('update-order-status/<int:order_id>/<str:status>/', views.update_order_status_ajax, name='update_order_status_ajax'),
    
    # M-Pesa Payment URLs
    path('mpesa/initiate-payment/<int:order_id>/', views.initiatepayment, name='Mpesa_payment_initiation'),
    path('daraja/stk_push/', views.stk_push_callback, name='stk_push_callback'),
    
    # User Management
    path('user-management/', usermanage.user_management, name='user_management'),
    path('user/add/', usermanage.user_add, name='user_add'),
    path('user/<int:pk>/edit/', usermanage.user_edit, name='user_edit'),
    path('user/<int:pk>/delete/', usermanage.user_delete, name='user_delete'),
    path('user/<int:pk>/profile/', usermanage.user_profile, name='user_profile'),
    
    # Customer Management
    path('search-customers/', customers.search_customers, name='search_customers'),
    path('customer-management/', customers.customer_management, name='customer_management'),
    path('customer/add/', customers.customer_add, name='customer_add'),
    path('customer/<int:pk>/edit/', customers.customer_edit, name='customer_edit'),
    path('customer/<int:pk>/delete/', customers.customer_delete, name='customer_delete'),
    path('customer/<int:pk>/orders/', customers.customer_orders, name='customer_orders'),
    
    # Expense Management
    path("expenses/", Expenses.expense_list, name="expense_list"),
    path("expenses/create/", Expenses.expense_form, name="expense_form"),
    path("expenses/edit/<int:record_id>/", Expenses.edit_expense_record, name="edit_expense_record"),
    path("expenses/delete/<int:record_id>/", Expenses.delete_expense_record, name="delete_expense_record"),
    
    # Expense Fields Management
    path("expense-fields/create/", Expenses.create_expense_field, name="create_expense_field"),
    path("expense-fields/", Expenses.expense_field_list, name="expense_field_list"),
    path("expense-fields/edit/<int:field_id>/", Expenses.edit_expense_field, name="edit_expense_field"),
    path("expense-fields/delete/<int:field_id>/", Expenses.delete_expense_field, name="delete_expense_field"),
    
    # Debug URLs
     # Add debug URL
    path('debug-dashboard-data/', views.debug_dashboard_data, name='debug_dashboard_data'),
    #path('debug-urls/', views.debug_urls, name='debug_urls'),
    path('debug/financial-summary/', views.DebugFinancialDataView.as_view(), name='debug_financial_summary'),
    path('debug/quick-financial/', views.quick_financial_debug, name='quick_financial_debug'),
    path('debug/order-calculations/', views.debug_order_calculations, name='debug_order_calculations'),
]