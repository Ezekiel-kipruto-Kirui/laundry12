from django.contrib import admin
from django.urls import path,include
from . import views
from . Vews.expense import *
from django.views.decorators.cache import cache_page

# Create an instance of the admin class to access its methods

# from LaundryApp.admin import dashboard_view  # Import your new view
app_name = "hotel"
urlpatterns = [
    path('categories/', views.category_list, name='category_list'),
    path('categories/create/', views.category_create, name='category_create'),
    path('categories/<int:pk>/edit/', views.category_edit, name='category_edit'),
    path('categories/<int:pk>/delete/', views.category_delete, name='category_delete'),
    
    # Food Item URLs
    path('load-default-food-items/', views.load_default_food_items, name='load_default_food_items'),
    path('items/', views.food_item_list, name='food_item_list'),
    path('items/create/', views.food_item_create, name='food_item_create'),
    path('items/<int:pk>/edit/', views.food_item_edit, name='food_item_edit'),
    path('items/<int:pk>/availability/', views.food_item_availability, name='food_item_availability'),
    path('items/<int:pk>/delete/', views.food_item_delete, name='food_item_delete'),
    
    # Order URLs
    # path('menu/', views.menu, name='menu'),
    path('order/create/', views.create_order, name='create_order'),
    # path('orders/', views.order_list, name='order_list'),
    # path('orders/<int:pk>/', views.order_detail, name='order_detail'),
    path('orders/', views.order_list, name='order_list'),
    path('orders/<int:pk>/', views.order_detail, name='order_detail'),
    path('orders/<int:pk>/edit/', views.order_edit, name='order_edit'),
    path('orders/<int:pk>/delete/', views.order_delete, name='order_delete'),
    path('orders/<int:pk>/update-ajax/', views.order_update_ajax, name='order_update_ajax'),

    # API URLs
    path('api/items/<int:pk>/', views.get_food_item_info, name='get_food_item_info'),

    # Business list page - shows Hotel and Laundry Shop
    path('expense-fields/create/', create_expense_field, name='createhotel_expense_field'),
    path('expense-fields/', expense_field_list, name='expense_field_list'),
    path('expense-fields/edit/<int:field_id>/',edit_expense_field, name='edit_expense_field'),
    path('expense-fields/delete/<int:field_id>/', delete_expense_field, name='delete_expense_field'),
    path('expenses/create/', expense_form, name='expense_form'),
    path('expenses/', expense_list, name='expense_list'),
    path('expenses/edit/<int:record_id>/', edit_expense_record, name='edit_expense_record'),
    path('expenses/delete/<int:record_id>/', delete_expense_record, name='delete_expense_record'),
   


]