"""
Django admin configuration for LaundryApp.

This module contains all admin classes and configurations for the laundry management system,
including custom forms, inlines, actions, and dashboard functionality.
"""

# Standard library imports
import logging
from functools import wraps

# Django core imports
from django import forms
from django.contrib import admin, messages
from django.contrib.admin import register
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group, User
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render, redirect
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.timezone import now
from django.views.decorators.cache import cache_page
from django.db.models import Q, Count, DecimalField, Max, Sum
from django.db.models import Value
from django.db.models.functions import Coalesce
from django.http import JsonResponse

# Third-party imports
from import_export.admin import ImportExportModelAdmin
from unfold.admin import ModelAdmin
from unfold.contrib.filters.admin import RangeDateFilter
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm
from unfold.widgets import (
    UnfoldAdminDateWidget,
    UnfoldAdminSelectWidget,
    UnfoldAdminTextareaWidget,
    UnfoldAdminTextInputWidget,
)

# Local imports
from .models import Customer, Order, OrderItem, Payment
from .analytics import DashboardAnalytics
from .forms import CustomerForm, OrderForm, OrderItemForm, PaymentForm

# Setup logger
logger = logging.getLogger(__name__)

# Unregister default User and Group
admin.site.unregister(User)
admin.site.unregister(Group)

# --- Utility Functions ---
def permission_required(perm_code):
    """Decorator to check permissions for admin actions."""
    def decorator(func):
        @wraps(func)
        def wrapper(self, request, queryset):
            if not request.user.is_superuser and not request.user.has_perm(perm_code):
                logger.warning(
                    f"User {request.user.username} attempted action '{func.__name__}' "
                    f"without permission '{perm_code}'"
                )
                self.message_user(
                    request,
                    f"You do not have permission to perform this action. Required: {perm_code}",
                    level=messages.ERROR
                )
                return HttpResponseRedirect(request.get_full_path())
            return func(self, request, queryset)
        return wrapper
    return decorator

# --- Base Admin Classes ---
class SuperuserOnlyMixin:
    """Mixin to restrict access to superusers only."""
    
    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser


class AppPermissionMixin:
    """Mixin for checking permissions based on app label and model name."""
    
    model_name = ""

    def _get_permission(self, action):
        return f'LaundryApp.{action}_{self.model_name}'

    def has_add_permission(self, request):
        return request.user.is_superuser or request.user.has_perm(self._get_permission('add'))

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser or request.user.has_perm(self._get_permission('change'))

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser or request.user.has_perm(self._get_permission('delete'))

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser or request.user.has_perm(self._get_permission('view'))


class ShopPermissionMixin:
    """Mixin for filtering querysets based on user's shop groups."""
    
    def get_user_shops(self, request):
        if request.user.is_superuser:
            return None

        user_groups = request.user.groups.values_list('name', flat=True)
        shops = []

        if 'Shop A' in user_groups:
            shops.append('Shop A')
        if 'Shop B' in user_groups:
            shops.append('Shop B')

        return shops if shops else []

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        user_shops = self.get_user_shops(request)

        if user_shops is None:
            return queryset
        elif user_shops:
            return self.filter_by_shops(queryset, user_shops)
        else:
            return queryset.none()

    def filter_by_shops(self, queryset, shops):
        return queryset

    def object_belongs_to_user_shops(self, obj, user_shops):
        return True

# --- Group and User Admin ---
@admin.register(Group)
class GroupAdmin(SuperuserOnlyMixin, ModelAdmin):
    """Admin interface for Django Groups."""
    
    list_display = ('name', 'user_count')
    search_fields = ('name',)
    ordering = ('name',)

    def user_count(self, obj):
        return obj.user_set.count()
    user_count.short_description = 'Users'
    user_count.admin_order_field = 'user_count'


@admin.register(User)
class UserAdmin(BaseUserAdmin, ModelAdmin):
    """Custom User admin interface with enhanced security controls."""
    
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm
    list_display = ('username', 'email', 'first_name', 'last_name', 'is_staff', 'is_superuser', 'get_groups')
    list_filter = ('is_staff', 'is_superuser', 'groups', 'is_active')
    search_fields = ('username', 'first_name', 'last_name', 'email')
    ordering = ('username',)

    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Personal info", {"fields": ("first_name", 'last_name', "email")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('groups')

    def get_actions(self, request):
        actions = super().get_actions(request)
        if request.user.is_staff and not request.user.is_superuser:
            return {}
        return actions

    def has_module_permission(self, request):
        return request.user.is_superuser

    def get_groups(self, obj):
        return ", ".join([group.name for group in obj.groups.all()])
    get_groups.short_description = 'Groups'

    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser and obj.is_superuser:
            logger.warning(
                f"Non-superuser {request.user.username} attempted to grant "
                f"superuser status to {obj.username}"
            )
            obj.is_superuser = False
        super().save_model(request, obj, form, change)

# --- Customer Admin ---
class CustomerAdminForm(forms.ModelForm):
    """Custom form for Customer admin with enhanced widgets."""
    
    class Meta:
        model = Customer
        fields = "__all__"
        widgets = {
            "name": UnfoldAdminTextInputWidget(),
            "phone": UnfoldAdminTextInputWidget(),
        }

@admin.register(Customer)
class CustomerAdmin(ShopPermissionMixin, AppPermissionMixin, ModelAdmin, ImportExportModelAdmin):
    """Admin interface for Customer model."""
    
    model_name = "customer"
    list_display = ('name', 'phone', 'last_order_date', 'total_spent', 'order_count')
    list_display_links = ('name', 'phone')
    search_fields = ('name', 'phone')
    list_per_page = 20
    ordering = ('name',)
    form = CustomerAdminForm
    actions = ['mass_delete_customers']

    fieldsets = (
        (None, {
            'fields': ('name', 'phone'),
            'classes': ('border', 'border-gray-200', 'rounded-lg', 'p-4', 'mb-4'),
            'description': 'Basic customer information'
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            order_count=Count('orders'),
            last_order_date=Max('orders__delivery_date'),
            total_spent=Coalesce(Sum('orders__total_price'), Value(0), output_field=DecimalField())
        )

    def filter_by_shops(self, queryset, shops):
        return queryset.filter(orders__shop__in=shops).distinct()

    def object_belongs_to_user_shops(self, obj, user_shops):
        return obj.orders.filter(shop__in=user_shops).exists()

    def last_order_date(self, obj):
        return obj.last_order_date if obj.last_order_date else "No orders"
    last_order_date.short_description = 'Last Order'
    last_order_date.admin_order_field = 'last_order_date'

    def total_spent(self, obj):
        return format_html('<span class="font-medium text-green-600">KSh {}</span>', f'{obj.total_spent:,.2f}')
    total_spent.short_description = 'Total Spent'
    total_spent.admin_order_field = 'total_spent'

    def order_count(self, obj):
        return format_html('<span class="px-2 py-1 bg-blue-100 text-blue-800 rounded-full text-xs font-medium">{}</span>', obj.order_count)
    order_count.short_description = 'Orders'
    order_count.admin_order_field = 'order_count'

    @permission_required('LaundryApp.delete_customer')
    def mass_delete_customers(self, request, queryset):
        if 'apply' in request.POST:
            try:
                deleted_count, _ = queryset.delete()
                logger.info(f"User {request.user.username} deleted {deleted_count} customers")
                self.message_user(
                    request,
                    f"Successfully deleted {deleted_count} customers.",
                    level=messages.SUCCESS
                )
                return HttpResponseRedirect(request.get_full_path())
            except Exception as e:
                logger.error(f"Error deleting customers: {e}")
                self.message_user(
                    request,
                    "An error occurred while deleting customers.",
                    level=messages.ERROR
                )
                return HttpResponseRedirect(request.get_full_path())

        return render(request, 'admin/confirm_delete.html', {
            'queryset': queryset,
            'title': "Are you sure?",
            'action_name': "mass_delete_customers",
        })
    mass_delete_customers.short_description = "Delete selected customers"

# -- OrderItem Inline Admin ---
class OrderItemInlineForm(forms.ModelForm):
    """Custom form for OrderItem inline admin."""
    
    class Meta:
        model = OrderItem
        fields = "__all__"
        widgets = {
            "servicetype": UnfoldAdminSelectWidget(),
            "itemtype": UnfoldAdminSelectWidget(),
            "itemname": UnfoldAdminTextareaWidget(),
            "itemcondition": UnfoldAdminSelectWidget(),
            "quantity": UnfoldAdminTextInputWidget(),
            "additional_info": UnfoldAdminTextareaWidget(),
            "unit_price": UnfoldAdminTextInputWidget(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and self.instance.itemname:
            self.fields['itemname'].widget.attrs['data-values'] = self.instance.itemname.split(', ')

    def clean_itemname(self):
        data = self.cleaned_data.get('itemname', '')
        if isinstance(data, list):
            items = [item.strip() for item in data if item.strip()]
        elif isinstance(data, str):
            items = [item.strip() for item in data.split(',') if item.strip()]
        else:
            items = []
        return ', '.join(items)

    def clean_quantity(self):
        quantity = self.cleaned_data.get('quantity')
        if quantity and quantity <= 0:
            raise forms.ValidationError("Quantity must be greater than 0.")
        return quantity

    def clean_unit_price(self):
        unit_price = self.cleaned_data.get('unit_price')
        if unit_price and unit_price <= 0:
            raise forms.ValidationError("Unit price must be greater than 0.")
        return unit_price


class OrderItemInline(admin.TabularInline):
    """Inline admin for OrderItem model."""
    
    model = OrderItem
    form = OrderItemInlineForm
    extra = 1
    min_num = 1
    fields = ('servicetype', 'itemtype', 'itemname', 'quantity', 'itemcondition',
              'unit_price', 'additional_info', 'total_item_price')
    readonly_fields = ('total_item_price',)

    def total_item_price(self, obj):
        if obj.pk:
            total = (obj.unit_price or 0) * (obj.quantity or 0)
            return format_html('<span class="font-medium text-green-600">KSh {}</span>', f'{total:,.2f}')
        return "Save to calculate"
    total_item_price.short_description = 'Total Price'

@admin.register(Payment)
class PaymentAdmin(ShopPermissionMixin, AppPermissionMixin, ModelAdmin):
    """Admin interface for Payment model."""
    
    model_name = "payment"
    list_display = ('order_link', 'price', 'payment_date', 'payment_method')
    list_display_links = ('order_link', 'price')
    list_filter = ('payment_method', 'payment_date')
    search_fields = ('order__uniquecode', 'transaction_id')
    ordering = ('-payment_date',)
    readonly_fields = ('price',)

    def order_link(self, obj):
        if not obj.order:
            return "-"
        link = reverse("admin:LaundryApp_order_change", args=[obj.order.pk])
        return format_html(
            '<a class="text-primary-600 hover:text-primary-800 underline" href="{}">{}</a>',
            link, obj.order.uniquecode
        )
    order_link.short_description = 'Order'
    order_link.admin_order_field = 'order__uniquecode'

    def filter_by_shops(self, queryset, shops):
        return queryset.filter(order__shop__in=shops)

    def object_belongs_to_user_shops(self, obj, user_shops):
        return obj.order and obj.order.shop in user_shops

# --- Order Admin ---
class OrderAdminForm(forms.ModelForm):
    """Custom form for Order admin with enhanced widgets."""
    
    class Meta:
        model = Order
        fields = "__all__"
        widgets = {
            "customer": UnfoldAdminSelectWidget(),
            "payment_type": UnfoldAdminSelectWidget(),
            "payment_status": UnfoldAdminSelectWidget(),
            "delivery_date": UnfoldAdminDateWidget(),
            "order_status": UnfoldAdminSelectWidget(),
            "address": UnfoldAdminTextInputWidget(),
            "addressdetails": UnfoldAdminTextareaWidget(),
            "shop": UnfoldAdminSelectWidget(),
        }

    def clean_delivery_date(self):
        delivery_date = self.cleaned_data.get('delivery_date')
        if delivery_date and delivery_date < now().date():
            raise forms.ValidationError("Delivery date cannot be in the past.")
        return delivery_date


@admin.register(Order)
class OrderAdmin(ShopPermissionMixin, AppPermissionMixin, ModelAdmin, ImportExportModelAdmin):
    """Comprehensive admin interface for Order model."""
    
    model_name = "order"
    list_display = (
        'uniquecode', 'customer_link', 'items_count',
        'order_status', 'payment_status', 'delivery_date',
        'total_price_formatted', 'shop'
    )
    list_display_links = ('uniquecode', 'customer_link')
    list_filter = (
        'order_status', 'payment_status', ('delivery_date', RangeDateFilter),
        'shop', 'payment_type'
    )
    search_fields = (
        'uniquecode', 'customer__name', 'customer__phone', 'shop'
    )
    readonly_fields = ('uniquecode', 'total_price')
    list_per_page = 25
    ordering = ('-created_at',)
    form = OrderAdminForm
    inlines = [OrderItemInline]
    actions = ['update_status_to_completed', 'update_status_to_delivered', 'delete_selected']

    fieldsets = (
        ('Order Information', {
            'fields': (
                ('customer', 'shop'),
                ('payment_type', 'payment_status'),
            ),
            'classes': ('border', 'border-gray-200', 'rounded', 'p-4', 'mb-4'),
        }),
        ('Pricing', {
            'fields': (('total_price',),),
            'classes': ('border', 'border-gray-200', 'rounded', 'p-4', 'mb-4'),
        }),
        ('Delivery Details', {
            'fields': (
                ('delivery_date', 'order_status', 'address'),
                'addressdetails',
            ),
            'classes': ('border', 'border-gray-200', 'rounded', 'p-4', 'mb-4'),
        }),
    )
   
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.analytics = DashboardAnalytics(self)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            items_count=Count('items')
        )

    def filter_by_shops(self, queryset, shops):
        return queryset.filter(shop__in=shops)

    def object_belongs_to_user_shops(self, obj, user_shops):
        return obj.shop in user_shops

    def customer_link(self, obj):
        if not obj.customer:
            return "-"
        link = reverse("admin:LaundryApp_customer_change", args=[obj.customer.pk])
        return format_html(
            '<a class="text-primary-600 hover:text-primary-800 underline" href="{}">{}</a>',
            link, obj.customer.name
        )
    customer_link.short_description = 'Customer'
    customer_link.admin_order_field = 'customer__name'

    def items_count(self, obj):
        count = getattr(obj, 'items_count', 0)
        return format_html(
            '<span class="px-2 py-1 bg-blue-100 text-blue-800 rounded-full text-xs font-medium">{}</span>',
            count
        )
    items_count.short_description = 'Items'
    items_count.admin_order_field = 'items_count'

    def total_price_formatted(self, obj):
        return format_html(
            '<span class="font-medium text-primary-600">KSh {}</span>',
            f'{obj.total_price:,.2f}'
        )
    total_price_formatted.short_description = 'Total'
    total_price_formatted.admin_order_field = 'total_price'

    @permission_required('LaundryApp.change_order')
    def update_status_to_completed(self, request, queryset):
        try:
            updated_count = queryset.update(order_status='Completed')
            logger.info(f"User {request.user.username} marked {updated_count} orders as completed")
            self.message_user(
                request,
                f"{updated_count} orders were successfully marked as completed.",
                level=messages.SUCCESS
            )
        except Exception as e:
            logger.error(f"Error updating orders to completed: {e}")
            self.message_user(
                request,
                "An error occurred while updating orders.",
                level=messages.ERROR
            )
    update_status_to_completed.short_description = "Mark selected orders as completed"

    @permission_required('LaundryApp.change_order')
    def update_status_to_delivered(self, request, queryset):
        try:
            updated_count = queryset.update(order_status='Delivered')
            logger.info(f"User {request.user.username} marked {updated_count} orders as delivered")
            self.message_user(
                request,
                f"{updated_count} orders were successfully marked as delivered.",
                level=messages.SUCCESS
            )
        except Exception as e:
            logger.error(f"Error updating orders to delivered: {e}")
            self.message_user(
                request,
                "An error occurred while updating orders.",
                level=messages.ERROR
            )
    update_status_to_delivered.short_description = "Mark selected orders as delivered"

    

    def admin_order_form(self, request):
        """Admin version of the order form with enhanced customer handling"""
        if request.method == 'POST':
            customer_form = CustomerForm(request.POST)
            order_form = OrderForm(request.POST)
            order_item_form = OrderItemForm(request.POST)
            payment_form = PaymentForm(request.POST)
            # Check if this is a customer existence check
            if (request.headers.get('X-Requested-With') == 'XMLHttpRequest' and
                'check_customer' in request.POST):
                phone = request.POST.get('phone', '')
                customer = Customer.objects.filter(phone=phone).first()
                if customer:
                    return JsonResponse({
                        'exists': True,
                        'customer': {
                            'id': customer.id,
                            'name': customer.name,
                            'phone': str(customer.phone)
                        }
                    })
                return JsonResponse({'exists': False})

            # Check if this is an AJAX request for customer creation
            if (request.headers.get('X-Requested-With') == 'XMLHttpRequest' and
                'customer_only' in request.POST):
                if customer_form.is_valid():
                    try:
                        # Double-check if customer already exists
                        phone = customer_form.cleaned_data.get('phone')
                        existing_customer = Customer.objects.filter(phone=phone).first()
                        if existing_customer:
                            request.session['customer_id'] = existing_customer.id
                            return JsonResponse({
                                'success': True,
                                'customer_id': existing_customer.id,
                                'existing_customer': True,
                                'message': f'Customer already exists: {existing_customer.name}'
                            })

                        customer = customer_form.save()
                        request.session['customer_id'] = customer.id
                        return JsonResponse({
                            'success': True,
                            'customer_id': customer.id,
                            'message': 'New customer created successfully'
                        })
                    except Exception as e:
                        return JsonResponse({
                            'success': False,
                            'message': f'Error saving customer: {str(e)}'
                        })
                else:
                    return JsonResponse({
                        'success': False,
                        'message': 'Please correct the errors',
                        'errors': customer_form.errors.get_json_data()
                    })

            # Check if this is a step submission (AJAX)
            if (request.headers.get('X-Requested-With') == 'XMLHttpRequest' and
                'step_submit' in request.POST):
                current_step = int(request.POST.get('current_step', 1))
                forms_valid = True
                errors = {}

                # Validate only the forms relevant to the current step
                if current_step == 1:
                    if not customer_form.is_valid():
                        forms_valid = False
                        errors.update(customer_form.errors.get_json_data())
                elif current_step == 2:
                    if not order_form.is_valid():
                        forms_valid = False
                        errors.update(order_form.errors.get_json_data())
                elif current_step == 3:
                    if not order_item_form.is_valid():
                        forms_valid = False
                        errors.update(order_item_form.errors.get_json_data())
                elif current_step == 4:
                    if not payment_form.is_valid():
                        forms_valid = False
                        errors.update(payment_form.errors.get_json_data())

                # If forms are valid, try to save the data
                if forms_valid:
                    try:
                        # Save data based on current step
                        if current_step == 1:
                            # Enhanced customer handling
                            phone = request.POST.get('phone', '')
                            name = request.POST.get('name', '')

                            # Check if customer already exists
                            existing_customer = Customer.objects.filter(phone=phone).first()

                            if existing_customer:
                                # Use existing customer
                                request.session['customer_id'] = existing_customer.id
                                return JsonResponse({
                                    'success': True,
                                    'customer_id': existing_customer.id,
                                    'existing_customer': True,
                                    'customer_name': existing_customer.name,
                                    'message': f'Using existing customer: {existing_customer.name}'
                                })
                            else:
                                # Create new customer
                                customer = customer_form.save()
                                request.session['customer_id'] = customer.id
                                return JsonResponse({
                                    'success': True,
                                    'customer_id': customer.id,
                                    'message': 'New customer created successfully'
                                })

                        elif current_step == 2:
                            if 'customer_id' in request.session:
                                order = order_form.save(commit=False)
                                order.customer_id = request.session['customer_id']
                                order.save()
                                request.session['order_id'] = order.id
                                return JsonResponse({
                                    'success': True,
                                    'order_id': order.id
                                })
                            else:
                                return JsonResponse({
                                    'success': False,
                                    'message': 'Customer information is missing. Please start from step 1.'
                                })

                        elif current_step == 3:
                            if 'order_id' in request.session:
                                order_item = order_item_form.save(commit=False)
                                order_item.order_id = request.session['order_id']
                                order_item.save()

                                # Update order total price
                                order = Order.objects.get(id=request.session['order_id'])
                                order.total_price = (order_item.unit_price or 0) * (order_item.quantity or 0)
                                order.save()

                                return JsonResponse({
                                    'success': True
                                })
                            else:
                                return JsonResponse({
                                    'success': False,
                                    'message': 'Order information is missing. Please start from step 2.'
                                })

                        elif current_step == 4:
                            if 'order_id' in request.session:
                                payment = payment_form.save(commit=False)
                                payment.order_id = request.session['order_id']

                                # Get order total price
                                order = Order.objects.get(id=request.session['order_id'])
                                payment.price = order.total_price
                                payment.payment_date = now()
                                payment.save()

                                # Clear session data
                                if 'customer_id' in request.session:
                                    del request.session['customer_id']
                                if 'order_id' in request.session:
                                    del request.session['order_id']

                                return JsonResponse({
                                    'success': True,
                                    'redirect_url': reverse('admin:laundryapp_order_success')
                                })
                            else:
                                return JsonResponse({
                                    'success': False,
                                    'message': 'Order information is missing. Please start from step 2.'
                                })

                    except Exception as e:
                        return JsonResponse({
                            'success': False,
                            'message': f'Error saving data: {str(e)}'
                        })

                else:
                    # Return validation errors
                    return JsonResponse({
                        'success': False,
                        'message': 'Please correct the errors',
                        'errors': errors
                    })

            # Regular form submission (all forms at once)
            if (customer_form.is_valid() and order_form.is_valid() and
                order_item_form.is_valid() and payment_form.is_valid()):

                try:
                    # Enhanced customer handling for regular submission
                    phone = request.POST.get('phone', '')
                    existing_customer = Customer.objects.filter(phone=phone).first()

                    if existing_customer:
                        customer = existing_customer
                        messages.info(request, f'Using existing customer: {existing_customer.name}')
                    else:
                        # Save customer
                        customer = customer_form.save()
                        messages.success(request, 'New customer created successfully')

                    # Save order with customer reference
                    order = order_form.save(commit=False)
                    order.customer = customer
                    order.total_price = 0
                    order.save()

                    # Save order item with order reference
                    order_item = order_item_form.save(commit=False)
                    order_item.order = order
                    order_item.save()

                    # Calculate total price
                    order.total_price = (order_item.unit_price or 0) * (order_item.quantity or 0)
                    order.save()

                    # Save payment with order reference
                    payment = payment_form.save(commit=False)
                    payment.order = order
                    payment.price = order.total_price
                    payment.payment_date = now()
                    payment.save()

                    messages.success(request, f'Order {order.uniquecode} created successfully!')
                    return redirect('admin:laundryapp_order_success')

                except Exception as e:
                    messages.error(request, f'Error saving order: {str(e)}')

            else:
                messages.error(request, 'Please correct the errors below.')

        else:
            customer_form = CustomerForm()
            order_form = OrderForm()
            order_item_form = OrderItemForm()
            payment_form = PaymentForm()

        context = {
            'customer_form': customer_form,
            'order_form': order_form,
            'order_item_form': order_item_form,
            'payment_form': payment_form,
            'title': 'New Laundry Order',
            'is_admin': True,  # Flag to indicate this is admin interface
            **self.admin_site.each_context(request),
        }

        return render(request, 'order_form.html', context)

    def admin_order_success(self, request):
        """Admin order success page"""
        context = {
            'title': 'Order Success',
            **self.admin_site.each_context(request),
        }
        return render(request, 'order_success.html', context)

    @permission_required('LaundryApp.delete_order')
    def delete_selected(self, request, queryset):
        if 'apply' in request.POST:
            try:
                deleted_count, _ = queryset.delete()
                logger.info(f"User {request.user.username} deleted {deleted_count} orders")
                self.message_user(
                    request,
                    f"Successfully deleted {deleted_count} orders.",
                    level=messages.SUCCESS
                )
                return HttpResponseRedirect(request.get_full_path())
            except Exception as e:
                logger.error(f"Error deleting orders: {e}")
                self.message_user(
                    request,
                    "An error occurred while deleting orders.",
                    level=messages.ERROR
                )
                return HttpResponseRedirect(request.get_full_path())

        return render(request, 'admin/confirm_delete.html', {
            'queryset': queryset,
            'title': "Are you sure?",
            'action_name': "delete_selected",
        })
    delete_selected.short_description = "Delete selected orders"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('dashboard/', self.admin_site.admin_view(cache_page(60 * 5)(self.dashboard_view)),
                 name='laundryapp_dashboard'),
            path('new-order/', self.admin_site.admin_view(self.admin_order_form),
                 name='laundryapp_new_order'),
            path('new-order/success/', self.admin_site.admin_view(self.admin_order_success),
                 name='laundryapp_order_success'),
        ]
        return custom_urls + urls

    def dashboard_view(self, request):
        if not request.user.is_superuser:
            logger.warning(f"Non-superuser {request.user.username} attempted to access dashboard")
            raise Http404("You do not have permission to access this dashboard.")

        current_year = now().year
        try:
            selected_year = int(request.GET.get('year', current_year))
            if selected_year < 2020 or selected_year > current_year + 1:
                selected_year = current_year
        except (ValueError, TypeError):
            selected_year = current_year

        selected_month = None
        selected_month_str = request.GET.get('month')
        if selected_month_str and len(selected_month_str) == 7 and selected_month_str[4] == '-':
            try:
                selected_month = int(selected_month_str.split('-')[1])
                if selected_month < 1 or selected_month > 12:
                    selected_month = None
            except (ValueError, IndexError):
                selected_month = None

        data = self.analytics.get_dashboard_data(request, selected_year, selected_month)
        context = self.analytics.prepare_dashboard_context(request, data, selected_year, selected_month)
        
        context.update(self.admin_site.each_context(request))

        return render(request, 'Admin/laundry_dashboard.html', context)