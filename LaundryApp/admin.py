# laundry/LaundryApp/admin.py
"""
Django admin configuration for LaundryApp.

This module contains all admin classes and configurations for the laundry management system,
including custom forms, inlines, actions, and dashboard functionality.
"""

# Standard library imports
import hashlib
import json
import logging
from collections import Counter
from functools import wraps

# Django core imports
from django import forms
from django.contrib import admin, messages  # type: ignore[import]
from django.contrib.admin import register
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group, User
from django.db.models import (
    Avg, Count, DecimalField, Max, Q, Sum
)
from django.db.models.functions import Coalesce, ExtractMonth, ExtractYear
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.timezone import now
from django.views.decorators.cache import cache_page

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

# Setup logger
logger = logging.getLogger(__name__)

# Unregister default User and Group
admin.site.unregister(User)
admin.site.unregister(Group)

# --- Constants ---
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# --- Utility Functions ---
def permission_required(perm_code):
    """
    Decorator to check permissions for admin actions.

    Args:
        perm_code (str): The permission code required to perform the action.

    Returns:
        function: Decorated function that checks permissions before execution.

    Raises:
        HttpResponseRedirect: If user lacks required permissions.
    """
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
    """
    A mixin to restrict access to superusers only.

    This mixin overrides all permission methods to ensure that only superusers
    can perform any operations on the admin interface for models using this mixin.
    """

    def has_module_permission(self, request):
        """
        Check if user has permission to access this module.

        Args:
            request: The current request object.

        Returns:
            bool: True if user is superuser, False otherwise.
        """
        return request.user.is_superuser

    def has_add_permission(self, request):
        """
        Check if user has permission to add new objects.

        Args:
            request: The current request object.

        Returns:
            bool: True if user is superuser, False otherwise.
        """
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        """
        Check if user has permission to change objects.

        Args:
            request: The current request object.
            obj: The object being changed (optional).

        Returns:
            bool: True if user is superuser, False otherwise.
        """
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        """
        Check if user has permission to delete objects.

        Args:
            request: The current request object.
            obj: The object being deleted (optional).

        Returns:
            bool: True if user is superuser, False otherwise.
        """
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        """
        Check if user has permission to view objects.

        Args:
            request: The current request object.
            obj: The object being viewed (optional).

        Returns:
            bool: True if user is superuser, False otherwise.
        """
        return request.user.is_superuser


class AppPermissionMixin:
    """
    A mixin for checking permissions based on the app label and model name.

    This mixin provides fine-grained permission control based on Django's
    permission system, allowing non-superusers to perform actions if they
    have the appropriate permissions.

    Attributes:
        model_name (str): The name of the model for permission checking.
    """
    model_name = ""

    def _get_permission(self, action):
        """
        Generate permission code for the given action.

        Args:
            action (str): The action type (add, change, delete, view).

        Returns:
            str: The full permission code (e.g., 'LaundryApp.add_customer').
        """
        return f'LaundryApp.{action}_{self.model_name}'

    def has_add_permission(self, request):
        """
        Check if user has permission to add new objects.

        Args:
            request: The current request object.

        Returns:
            bool: True if user is superuser or has add permission.
        """
        return request.user.is_superuser or request.user.has_perm(self._get_permission('add'))

    def has_change_permission(self, request, obj=None):
        """
        Check if user has permission to change objects.

        Args:
            request: The current request object.
            obj: The object being changed (optional).

        Returns:
            bool: True if user is superuser or has change permission.
        """
        return request.user.is_superuser or request.user.has_perm(self._get_permission('change'))

    def has_delete_permission(self, request, obj=None):
        """
        Check if user has permission to delete objects.

        Args:
            request: The current request object.
            obj: The object being deleted (optional).

        Returns:
            bool: True if user is superuser or has delete permission.
        """
        return request.user.is_superuser or request.user.has_perm(self._get_permission('delete'))

    def has_view_permission(self, request, obj=None):
        """
        Check if user has permission to view objects.

        Args:
            request: The current request object.
            obj: The object being viewed (optional).

        Returns:
            bool: True if user is superuser or has view permission.
        """
        return request.user.is_superuser or request.user.has_perm(self._get_permission('view'))


class ShopPermissionMixin:
    """
    A mixin for filtering querysets based on user's shop groups.

    This mixin restricts data access based on user groups:
    - Superusers can see all data
    - Users in 'Shop A' group can only see Shop A data
    - Users in 'Shop B' group can only see Shop B data
    - Users with no matching groups see no data
    """

    def get_user_shops(self, request):
        """
        Get the shops that the user has access to based on their groups.

        Args:
            request: The current request object.

        Returns:
            list: List of shop names the user can access, or None for all shops.
        """
        if request.user.is_superuser:
            return None  # Superuser can see all shops

        user_groups = request.user.groups.values_list('name', flat=True)
        shops = []

        # Map group names to shop names
        if 'Shop A' in user_groups:
            shops.append('Shop A')
        if 'Shop B' in user_groups:
            shops.append('Shop B')

        return shops if shops else []

    def get_queryset(self, request):
        """
        Filter the queryset based on user's shop permissions.

        Args:
            request: The current request object.

        Returns:
            QuerySet: Filtered queryset based on user permissions.
        """
        queryset = super().get_queryset(request)
        user_shops = self.get_user_shops(request)

        if user_shops is None:
            # Superuser - return all records
            return queryset
        elif user_shops:
            # Filter by user's shops
            return self.filter_by_shops(queryset, user_shops)
        else:
            # No shop access - return empty queryset
            return queryset.none()

    def filter_by_shops(self, queryset, shops):
        """
        Filter the queryset by shop names. Override in subclasses for specific filtering.

        Args:
            queryset: The base queryset to filter.
            shops: List of shop names to filter by.

        Returns:
            QuerySet: Filtered queryset.
        """
        # Default implementation - subclasses should override this
        return queryset

    def has_change_permission(self, request, obj=None):
        """
        Check if user has permission to change objects, considering shop restrictions.

        Args:
            request: The current request object.
            obj: The object being changed (optional).

        Returns:
            bool: True if user has permission.
        """
        if not super().has_change_permission(request, obj):
            return False

        if obj and not request.user.is_superuser:
            user_shops = self.get_user_shops(request)
            if user_shops and not self.object_belongs_to_user_shops(obj, user_shops):
                return False

        return True

    def has_delete_permission(self, request, obj=None):
        """
        Check if user has permission to delete objects, considering shop restrictions.

        Args:
            request: The current request object.
            obj: The object being deleted (optional).

        Returns:
            bool: True if user has permission.
        """
        if not super().has_delete_permission(request, obj):
            return False

        if obj and not request.user.is_superuser:
            user_shops = self.get_user_shops(request)
            if user_shops and not self.object_belongs_to_user_shops(obj, user_shops):
                return False

        return True

    def has_view_permission(self, request, obj=None):
        """
        Check if user has permission to view objects, considering shop restrictions.

        Args:
            request: The current request object.
            obj: The object being viewed (optional).

        Returns:
            bool: True if user has permission.
        """
        if not super().has_view_permission(request, obj):
            return False

        if obj and not request.user.is_superuser:
            user_shops = self.get_user_shops(request)
            if user_shops and not self.object_belongs_to_user_shops(obj, user_shops):
                return False

        return True

    def object_belongs_to_user_shops(self, obj, user_shops):
        """
        Check if an object belongs to the user's shops. Override in subclasses.

        Args:
            obj: The object to check.
            user_shops: List of shop names the user has access to.

        Returns:
            bool: True if object belongs to user's shops.
        """
        # Default implementation - subclasses should override this
        return True

# --- Group and User Admin ---
@admin.register(Group)
class GroupAdmin(SuperuserOnlyMixin, ModelAdmin):
    """
    Admin interface for Django Groups.

    Provides a simplified interface for managing user groups with user count display.
    Restricted to superusers only.
    """
    list_display = ('name', 'user_count')
    search_fields = ('name',)
    ordering = ('name',)

    def user_count(self, obj):
        """
        Display the number of users in this group.

        Args:
            obj: The Group instance.

        Returns:
            int: Number of users in the group.
        """
        return obj.user_set.count()
    user_count.short_description = 'Users'
    user_count.admin_order_field = 'user_count'


@admin.register(User)
class UserAdmin(BaseUserAdmin, ModelAdmin):
    """
    Custom User admin interface with enhanced security controls.

    Extends Django's BaseUserAdmin with additional security measures and
    improved user management capabilities.
    """
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
        """
        Optimize queryset by prefetching related groups.

        Args:
            request: The current request object.

        Returns:
            QuerySet: Optimized queryset with prefetched groups.
        """
        return super().get_queryset(request).prefetch_related('groups')

    def get_actions(self, request):
        """
        Restrict bulk actions for non-superuser staff members.

        Args:
            request: The current request object.

        Returns:
            dict: Available actions based on user permissions.
        """
        actions = super().get_actions(request)
        if request.user.is_staff and not request.user.is_superuser:
            return {}
        return actions

    def has_module_permission(self, request):
        """
        Only superusers can access the User admin module.

        Args:
            request: The current request object.

        Returns:
            bool: True if user is superuser, False otherwise.
        """
        return request.user.is_superuser

    def get_groups(self, obj):
        """
        Display comma-separated list of user's groups.

        Args:
            obj: The User instance.

        Returns:
            str: Comma-separated group names.
        """
        return ", ".join([group.name for group in obj.groups.all()])
    get_groups.short_description = 'Groups'

    def save_model(self, request, obj, form, change):
        """
        Prevent non-superusers from granting superuser status.

        Args:
            request: The current request object.
            obj: The User instance being saved.
            form: The form instance.
            change: Boolean indicating if this is an update.
        """
        if not request.user.is_superuser and obj.is_superuser:
            logger.warning(
                f"Non-superuser {request.user.username} attempted to grant "
                f"superuser status to {obj.username}"
            )
            obj.is_superuser = False
        super().save_model(request, obj, form, change)

# --- Customer Admin ---
class CustomerAdminForm(forms.ModelForm):
    """
    Custom form for Customer admin with enhanced widgets.

    Provides custom widgets for better user experience in the admin interface.
    """

    class Meta:
        model = Customer
        fields = "__all__"
        widgets = {
            "name": UnfoldAdminTextInputWidget(),
            "phone": UnfoldAdminTextInputWidget(),
        }

    def clean_phone(self):
        """
        Validate and format phone number.

        Returns:
            str: Formatted phone number.

        Raises:
            forms.ValidationError: If phone number format is invalid.
        """
        phone = self.cleaned_data.get('phone')
        if phone:
            # Additional validation can be added here if needed
            pass
        return phone


@admin.register(Customer)
class CustomerAdmin(ShopPermissionMixin, AppPermissionMixin, ModelAdmin, ImportExportModelAdmin):
    """
    Admin interface for Customer model.

    Provides comprehensive customer management with order statistics,
    bulk operations, and import/export functionality.
    Includes shop-based filtering for users.
    """
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
        """
        Optimize queryset with customer statistics annotations and apply shop filtering.

        Args:
            request: The current request object.

        Returns:
            QuerySet: Annotated queryset with order statistics and shop filtering.
        """
        return super().get_queryset(request).annotate(
            order_count=Count('orders'),
            last_order_date=Max('orders__delivery_date'),
            total_spent=Coalesce(Sum('orders__total_price'), 0, output_field=DecimalField())
        )

    def filter_by_shops(self, queryset, shops):
        """
        Filter customers by shop names (customers who have orders in these shops).

        Args:
            queryset: The base queryset to filter.
            shops: List of shop names to filter by.

        Returns:
            QuerySet: Filtered queryset.
        """
        return queryset.filter(orders__shop__in=shops).distinct()

    def object_belongs_to_user_shops(self, obj, user_shops):
        """
        Check if a customer belongs to the user's shops (has orders in user's shops).

        Args:
            obj: The Customer instance to check.
            user_shops: List of shop names the user has access to.

        Returns:
            bool: True if customer has orders in user's shops.
        """
        return obj.orders.filter(shop__in=user_shops).exists()

    def last_order_date(self, obj):
        """
        Display the date of the customer's last order.

        Args:
            obj: The Customer instance.

        Returns:
            str: Formatted last order date or "No orders".
        """
        return obj.last_order_date if obj.last_order_date else "No orders"
    last_order_date.short_description = 'Last Order'
    last_order_date.admin_order_field = 'last_order_date'

    def total_spent(self, obj):
        """
        Display customer's total spending with currency formatting.

        Args:
            obj: The Customer instance.

        Returns:
            str: Formatted total spent amount.
        """
        return format_html('<span class="font-medium text-green-600">KSh {}</span>', f'{obj.total_spent:,.2f}')
    total_spent.short_description = 'Total Spent'
    total_spent.admin_order_field = 'total_spent'

    def order_count(self, obj):
        """
        Display order count with badge styling.

        Args:
            obj: The Customer instance.

        Returns:
            str: Formatted order count with badge.
        """
        return format_html('<span class="px-2 py-1 bg-blue-100 text-blue-800 rounded-full text-xs font-medium">{}</span>', obj.order_count)
    order_count.short_description = 'Orders'
    order_count.admin_order_field = 'order_count'

    @permission_required('LaundryApp.delete_customer')
    def mass_delete_customers(self, request, queryset):
        """
        Bulk delete customers with confirmation dialog.

        Args:
            request: The current request object.
            queryset: The queryset of customers to delete.

        Returns:
            HttpResponse: Redirect or confirmation template.
        """
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

# --- OrderItem Inline Admin ---
class AddMoreInput(forms.TextInput):
    """
    Custom text input widget for handling multiple comma-separated values.

    This widget provides a user-friendly interface for entering multiple
    items that are stored as a comma-separated string in the database.
    """
    template_name = "widgets/add_more_input.html"

    def __init__(self, attrs=None):
        """
        Initialize the widget with default styling attributes.

        Args:
            attrs (dict, optional): Additional HTML attributes.
        """
        default_attrs = {
            'class': 'px-3 py-2 border rounded-md shadow-sm focus:outline-none '
                    'focus:ring-2 focus:ring-blue-500 focus:border-blue-500 '
                    'block w-full sm:text-sm border-gray-300'
        }
        if attrs:
            default_attrs.update(attrs)
        super().__init__(default_attrs)

    def get_context(self, name, value, attrs):
        """
        Get the context for rendering the widget.

        Args:
            name (str): Field name.
            value: Field value.
            attrs (dict): HTML attributes.

        Returns:
            dict: Context dictionary with parsed values.
        """
        context = super().get_context(name, value, attrs)

        # Handle multiple values (comma-separated)
        if value:
            context['widget']['values'] = [v.strip() for v in value.split(',') if v.strip()]
        else:
            context['widget']['values'] = []

        return context


class OrderItemInlineForm(forms.ModelForm):
    """
    Custom form for OrderItem inline admin.

    Provides enhanced widgets and validation for order item management.
    """

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
        """
        Initialize form with enhanced widget configuration.

        Sets up data attributes for the itemname widget to handle
        existing comma-separated values.
        """
        super().__init__(*args, **kwargs)
        # Set initial values for the widget if instance exists
        if self.instance and self.instance.pk and self.instance.itemname:
            self.fields['itemname'].widget.attrs['data-values'] = self.instance.itemname.split(', ')

    def clean_itemname(self):
        """
        Clean and validate the itemname field.

        Handles both list and string inputs, ensuring proper formatting
        of comma-separated values.

        Returns:
            str: Cleaned comma-separated item names.

        Raises:
            forms.ValidationError: If validation fails.
        """
        data = self.cleaned_data.get('itemname', '')
        if isinstance(data, list):
            # Handle multiple values from the widget
            items = [item.strip() for item in data if item.strip()]
        elif isinstance(data, str):
            # Handle single string value
            items = [item.strip() for item in data.split(',') if item.strip()]
        else:
            items = []
        return ', '.join(items)

    def clean_quantity(self):
        """
        Validate quantity field.

        Returns:
            int: Validated quantity.

        Raises:
            forms.ValidationError: If quantity is invalid.
        """
        quantity = self.cleaned_data.get('quantity')
        if quantity and quantity <= 0:
            raise forms.ValidationError("Quantity must be greater than 0.")
        return quantity

    def clean_unit_price(self):
        """
        Validate unit price field.

        Returns:
            Decimal: Validated unit price.

        Raises:
            forms.ValidationError: If unit price is invalid.
        """
        unit_price = self.cleaned_data.get('unit_price')
        if unit_price and unit_price <= 0:
            raise forms.ValidationError("Unit price must be greater than 0.")
        return unit_price


class OrderItemInline(admin.TabularInline):
    """
    Inline admin for OrderItem model.

    Provides a tabular interface for managing order items within the Order admin.
    """
    model = OrderItem
    form = OrderItemInlineForm
    extra = 1
    min_num = 1
    fields = ('servicetype', 'itemtype', 'itemname', 'quantity', 'itemcondition',
              'unit_price', 'additional_info', 'total_item_price')
    readonly_fields = ('total_item_price',)

    def total_item_price(self, obj):
        """
        Calculate and display total price for the order item.

        Args:
            obj: The OrderItem instance.

        Returns:
            str: Formatted total price or placeholder text.
        """
        if obj.pk:
            total = (obj.unit_price or 0) * (obj.quantity or 0)
            return format_html('<span class="font-medium text-green-600">KSh {}</span>', f'{total:,.2f}')
        return "Save to calculate"
    total_item_price.short_description = 'Total Price'

@admin.register(Payment)
class PaymentAdmin(ShopPermissionMixin, AppPermissionMixin, ModelAdmin):
    """
    Admin interface for Payment model.

    Provides payment tracking and management with links to associated orders.
    Includes shop-based filtering for users.
    """
    model_name = "payment"
    list_display = ('order_link', 'price', 'payment_date', 'payment_method')
    list_display_links = ('order_link', 'price')
    list_filter = ('payment_method', 'payment_date')
    search_fields = ('order__uniquecode', 'transaction_id')
    ordering = ('-payment_date',)
    readonly_fields = ('price',)  # Price is auto-calculated

    def order_link(self, obj):
        """
        Display clickable link to the associated order.

        Args:
            obj: The Payment instance.

        Returns:
            str: HTML link to the order or dash if no order.
        """
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
        """
        Filter payments by shop names (payments for orders in these shops).

        Args:
            queryset: The base queryset to filter.
            shops: List of shop names to filter by.

        Returns:
            QuerySet: Filtered queryset.
        """
        return queryset.filter(order__shop__in=shops)

    def object_belongs_to_user_shops(self, obj, user_shops):
        """
        Check if a payment belongs to the user's shops (payment for order in user's shops).

        Args:
            obj: The Payment instance to check.
            user_shops: List of shop names the user has access to.

        Returns:
            bool: True if payment's order is in user's shops.
        """
        return obj.order and obj.order.shop in user_shops

# --- Order Admin ---
class OrderAdminForm(forms.ModelForm):
    """
    Custom form for Order admin with enhanced widgets.

    Provides custom widgets and validation for order management.
    """

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
        """
        Validate delivery date.

        Returns:
            date: Validated delivery date.

        Raises:
            forms.ValidationError: If date is in the past.
        """
        delivery_date = self.cleaned_data.get('delivery_date')
        if delivery_date and delivery_date < now().date():
            raise forms.ValidationError("Delivery date cannot be in the past.")
        return delivery_date

    def clean(self):
        """
        Perform cross-field validation.

        Returns:
            dict: Cleaned form data.

        Raises:
            forms.ValidationError: If validation fails.
        """
        cleaned_data = super().clean()
        # Add any cross-field validation logic here if needed
        return cleaned_data

@admin.register(Order)
class OrderAdmin(ShopPermissionMixin, AppPermissionMixin, ModelAdmin, ImportExportModelAdmin):
    """
    Comprehensive admin interface for Order model.

    Provides order management with inline items, bulk actions, dashboard integration,
    and comprehensive filtering and search capabilities.
    Includes shop-based filtering for users.
    """
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

    def get_queryset(self, request):
        """
        Optimize queryset with item count annotation and apply shop filtering.

        Args:
            request: The current request object.

        Returns:
            QuerySet: Annotated queryset with item counts and shop filtering.
        """
        return super().get_queryset(request).annotate(
            items_count=Count('items')
        )

    def filter_by_shops(self, queryset, shops):
        """
        Filter orders by shop names.

        Args:
            queryset: The base queryset to filter.
            shops: List of shop names to filter by.

        Returns:
            QuerySet: Filtered queryset.
        """
        return queryset.filter(shop__in=shops)

    def object_belongs_to_user_shops(self, obj, user_shops):
        """
        Check if an order belongs to the user's shops.

        Args:
            obj: The Order instance to check.
            user_shops: List of shop names the user has access to.

        Returns:
            bool: True if order belongs to user's shops.
        """
        return obj.shop in user_shops

    def customer_link(self, obj):
        """
        Display clickable link to the associated customer.

        Args:
            obj: The Order instance.

        Returns:
            str: HTML link to the customer or dash if no customer.
        """
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
        """
        Display item count with badge styling.

        Args:
            obj: The Order instance.

        Returns:
            str: Formatted item count with badge.
        """
        count = getattr(obj, 'items_count', 0)
        return format_html(
            '<span class="px-2 py-1 bg-blue-100 text-blue-800 rounded-full text-xs font-medium">{}</span>',
            count
        )
    items_count.short_description = 'Items'
    items_count.admin_order_field = 'items_count'

    def total_price_formatted(self, obj):
        """
        Display total price with currency formatting.

        Args:
            obj: The Order instance.

        Returns:
            str: Formatted total price.
        """
        return format_html(
            '<span class="font-medium text-primary-600">KSh {}</span>',
            f'{obj.total_price:,.2f}'
        )
    total_price_formatted.short_description = 'Total'
    total_price_formatted.admin_order_field = 'total_price'

    @permission_required('LaundryApp.change_order')
    def update_status_to_completed(self, request, queryset):
        """
        Bulk action to mark selected orders as completed.

        Args:
            request: The current request object.
            queryset: The queryset of orders to update.
        """
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
        """
        Bulk action to mark selected orders as delivered.

        Args:
            request: The current request object.
            queryset: The queryset of orders to update.
        """
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

    @permission_required('LaundryApp.delete_order')
    def delete_selected(self, request, queryset):
        """
        Bulk delete orders with confirmation dialog.

        Args:
            request: The current request object.
            queryset: The queryset of orders to delete.

        Returns:
            HttpResponse: Redirect or confirmation template.
        """
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
        ]
        return custom_urls + urls

    def _get_dashboard_data(self, request, selected_year, selected_month=None):
        """Optimized method to fetch dashboard data with shop-based filtering."""
        try:
            # Get user's accessible shops
            user_shops = self.get_user_shops(request)

            # Base queryset with year filter
            base_queryset = Order.objects.filter(delivery_date__year=selected_year)
            if selected_month:
                base_queryset = base_queryset.filter(delivery_date__month=selected_month)

            # Apply shop filtering if user is not superuser
            if user_shops is not None:  # Not superuser
                if user_shops:  # Has specific shops
                    base_queryset = base_queryset.filter(shop__in=user_shops)
                else:  # No shop access
                    # Return empty data for users with no shop access
                    return self._get_empty_dashboard_data()

            # Single aggregation query for order statistics
            order_stats = base_queryset.aggregate(
                total_orders=Count('id'),
                pending_orders=Count('id', filter=Q(order_status='pending')),
                completed_orders=Count('id', filter=Q(order_status='Completed')),
                delivered_orders=Count('id', filter=Q(order_status='Delivered')),
                total_revenue=Coalesce(Sum('total_price'), 0, output_field=DecimalField()),
                avg_order_value=Coalesce(Avg('total_price'), 0, output_field=DecimalField())
            )

            # Shop-specific statistics
            shop_a_stats = base_queryset.filter(shop='Shop A').aggregate(
                revenue=Coalesce(Sum('total_price'), 0, output_field=DecimalField()),
                total_orders=Count('id'),
                pending_orders=Count('id', filter=Q(order_status='pending')),
                completed_orders=Count('id', filter=Q(order_status='Completed'))
            )

            shop_b_stats = base_queryset.filter(shop='Shop B').aggregate(
                revenue=Coalesce(Sum('total_price'), 0, output_field=DecimalField()),
                total_orders=Count('id'),
                pending_orders=Count('id', filter=Q(order_status='pending')),
                completed_orders=Count('id', filter=Q(order_status='Completed'))
            )

            # Optimized queries with proper aggregation
            revenue_by_shop = list(base_queryset.values('shop').annotate(
                total_revenue=Sum('total_price')
            ).order_by('-total_revenue'))

            common_customers = list(base_queryset.values('customer__name').annotate(
                order_count=Count('id'),
                total_spent=Sum('total_price')
            ).order_by('-order_count')[:5])

            payment_methods = list(base_queryset.values('payment_type').annotate(
                count=Count('id')
            ).order_by('-count'))

            # OrderItem related data
            order_item_data = OrderItem.objects.filter(order__in=base_queryset)

            # FIXED: Changed .order('-count') to .order_by('-count')
            top_services = list(order_item_data.values('servicetype').annotate(
                count=Count('id')
            ).order_by('-count')[:5])

            # For common items, we need to handle the comma-separated values
            all_items = []
            for item in order_item_data:
                if item.itemname:
                    item_list = [i.strip() for i in item.itemname.split(',') if i.strip()]
                    all_items.extend(item_list)

            # Count item occurrences
            item_counter = Counter(all_items)
            common_items = [{'itemname': item, 'count': count} for item, count in item_counter.most_common(5)]

            service_types = list(order_item_data.values('servicetype').annotate(
                count=Count('id')
            ).order_by('-count'))

            # Monthly data for charts
            line_chart_data = []
            monthly_order_volume = []

            if not selected_month:
                # Get shops to display based on user permissions
                if user_shops is None:  # Superuser - show all shops
                    shops = [choice[0] for choice in Order._meta.get_field('shop').choices]
                else:  # Regular user - show only their shops
                    shops = user_shops

                for shop in shops:
                    monthly_data = base_queryset.filter(shop=shop).annotate(
                        month=ExtractMonth('delivery_date')
                    ).values('month').annotate(
                        revenue=Coalesce(Sum('total_price'), 0, output_field=DecimalField())
                    ).order_by('month')

                    revenue_by_month = {item['month']: float(item['revenue']) for item in monthly_data}
                    monthly_values = [revenue_by_month.get(month, 0) for month in range(1, 13)]

                    if any(monthly_values):
                        color_seed = shop.encode('utf-8')
                        hex_color = hashlib.md5(color_seed).hexdigest()[0:6]
                        line_chart_data.append({
                            'label': shop,
                            'data': monthly_values,
                            'borderColor': f'#{hex_color}',
                            'fill': False,
                            'months': MONTHS
                        })

                monthly_order_volume = [
                    base_queryset.filter(delivery_date__month=month).count()
                    for month in range(1, 13)
                ]

            return {
                'order_stats': order_stats,
                'revenue_by_shop': revenue_by_shop,
                'common_customers': common_customers,
                'payment_methods': payment_methods,
                'top_services': top_services,
                'common_items': common_items,
                'service_types': service_types,
                'line_chart_data': line_chart_data,
                'monthly_order_volume': monthly_order_volume,
                'shop_a_stats': shop_a_stats,
                'shop_b_stats': shop_b_stats,
            }
        
        except Exception as e:
            # Log error and return empty data to prevent template errors
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error in _get_dashboard_data: {e}")

            return self._get_empty_dashboard_data()

    def _get_empty_dashboard_data(self):
        """Return empty dashboard data structure."""
        return {
            'order_stats': {
                'total_orders': 0, 'pending_orders': 0, 'completed_orders': 0,
                'delivered_orders': 0, 'total_revenue': 0, 'avg_order_value': 0
            },
            'revenue_by_shop': [],
            'common_customers': [],
            'payment_methods': [],
            'top_services': [],
            'common_items': [],
            'service_types': [],
            'line_chart_data': [],
            'monthly_order_volume': [],
            'shop_a_stats': {
                'revenue': 0, 'total_orders': 0, 'pending_orders': 0, 'completed_orders': 0
            },
            'shop_b_stats': {
                'revenue': 0, 'total_orders': 0, 'pending_orders': 0, 'completed_orders': 0
            },
        }

    def dashboard_view(self, request):
        """
        Render the business dashboard with comprehensive analytics.

        Args:
            request: The current request object.

        Returns:
            HttpResponse: Rendered dashboard template.

        Raises:
            Http404: If user lacks superuser permission.
        """
        if not request.user.is_superuser:
            logger.warning(f"Non-superuser {request.user.username} attempted to access dashboard")
            raise Http404("You do not have permission to access this dashboard.")

        current_year = now().year
        try:
            selected_year = int(request.GET.get('year', current_year))
            # Validate year range
            if selected_year < 2020 or selected_year > current_year + 1:
                selected_year = current_year
        except (ValueError, TypeError):
            selected_year = current_year

        selected_month = None
        selected_month_str = request.GET.get('month')
        if selected_month_str and len(selected_month_str) == 7 and selected_month_str[4] == '-':
            try:
                selected_month = int(selected_month_str.split('-')[1])
                # Validate month range
                if selected_month < 1 or selected_month > 12:
                    selected_month = None
            except (ValueError, IndexError):
                selected_month = None

        data = self._get_dashboard_data(request, selected_year, selected_month)

        years = Order.objects.annotate(
            year=ExtractYear('delivery_date')
        ).values_list('year', flat=True).distinct().order_by('year')

        # Helper function to sanitize strings for JSON
        def sanitize_for_json(value):
            """Remove control characters and escape special characters for JSON."""
            if isinstance(value, str):
                # Remove control characters (ASCII 0-31 except tab, newline, carriage return)
                cleaned = ''.join(char for char in value if ord(char) >= 32 or char in '\t\n\r')
                # Escape backslashes and quotes for JSON safety
                cleaned = cleaned.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
                return cleaned
            elif isinstance(value, (int, float)):
                return value
            elif value is None:
                return None
            else:
                # Convert to string and sanitize
                return sanitize_for_json(str(value))

        # Sanitize data before JSON serialization
        sanitized_revenue_by_shop = [
            {'shop': sanitize_for_json(item['shop']), 'total_revenue': item['total_revenue']}
            for item in data['revenue_by_shop']
        ]

        sanitized_top_services = [
            {'servicetype': sanitize_for_json(item['servicetype']), 'count': item['count']}
            for item in data['top_services']
        ]

        sanitized_common_items = [
            {'itemname': sanitize_for_json(item['itemname']), 'count': item['count']}
            for item in data['common_items']
        ]

        sanitized_payment_methods = [
            {'payment_type': sanitize_for_json(item['payment_type']), 'count': item['count']}
            for item in data['payment_methods']
        ]

        sanitized_service_types = [
            {'servicetype': sanitize_for_json(item['servicetype']), 'count': item['count']}
            for item in data['service_types']
        ]

        # Sanitize line chart data labels
        sanitized_line_chart_data = []
        for series in data['line_chart_data']:
            sanitized_series = series.copy()
            sanitized_series['label'] = sanitize_for_json(series['label'])
            sanitized_line_chart_data.append(sanitized_series)

        context = {
            **self.admin_site.each_context(request),
            'title': 'Business Dashboard',
            'current_year': selected_year,
            'selected_month': selected_month,
            'years': list(years),

            'total_revenue': data['order_stats']['total_revenue'],
            'total_orders': data['order_stats']['total_orders'],
            'pending_orders': data['order_stats']['pending_orders'],
            'completed_orders': data['order_stats']['completed_orders'],
            'delivered_orders': data['order_stats']['delivered_orders'],
            'avg_order_value': data['order_stats']['avg_order_value'],

            # Shop-specific data
            'shop_a_revenue': data['shop_a_stats']['revenue'],
            'shop_a_total_orders': data['shop_a_stats']['total_orders'],
            'shop_a_pending_orders': data['shop_a_stats']['pending_orders'],
            'shop_a_completed_orders': data['shop_a_stats']['completed_orders'],

            'shop_b_revenue': data['shop_b_stats']['revenue'],
            'shop_b_total_orders': data['shop_b_stats']['total_orders'],
            'shop_b_pending_orders': data['shop_b_stats']['pending_orders'],
            'shop_b_completed_orders': data['shop_b_stats']['completed_orders'],

            'pie_chart_labels': json.dumps([item['shop'] for item in sanitized_revenue_by_shop]),
            'pie_chart_values': json.dumps([float(item['total_revenue']) for item in sanitized_revenue_by_shop]),

            'line_chart_data': json.dumps(sanitized_line_chart_data),

            'services_labels': json.dumps([item['servicetype'] for item in sanitized_top_services]),
            'services_counts': json.dumps([item['count'] for item in sanitized_top_services]),

            'item_labels': json.dumps([item['itemname'] for item in sanitized_common_items]),
            'item_counts': json.dumps([item['count'] for item in sanitized_common_items]),

            'payment_method_labels': json.dumps([item['payment_type'] for item in sanitized_payment_methods]),
            'payment_method_counts': json.dumps([item['count'] for item in sanitized_payment_methods]),

            'service_type_labels': json.dumps([item['servicetype'] for item in sanitized_service_types]),
            'service_type_counts': json.dumps([item['count'] for item in sanitized_service_types]),

            'monthly_order_volume': json.dumps(data['monthly_order_volume']),
            'common_customers': data['common_customers'],
        }

        return render(request, 'admin/laundry_dashboard.html', context)

# --- OrderItem Admin (standalone view) ---
@admin.register(OrderItem)
class OrderItemAdmin(ShopPermissionMixin, AppPermissionMixin, ModelAdmin):
    """
    Standalone admin interface for OrderItem model.

    Provides detailed view of individual order items with comprehensive
    display and filtering options.
    Includes shop-based filtering for users.
    """
    model_name = "orderitem"
    list_display = ('order_link', 'servicetype', 'itemtype', 'items_display','quantity', 'unit_price', 'total_item_price_formatted')
    list_display_links = ('order_link', 'servicetype')
    list_filter = ('servicetype', 'itemtype', 'itemcondition')
    search_fields = ('order__uniquecode', 'itemname', 'servicetype')
    list_per_page = 20
    ordering = ('-created_at',)
    list_select_related = ('order',)
    readonly_fields = ('items_list_display',)

    def get_queryset(self, request):
        """
        Optimize queryset with select_related for better performance and apply shop filtering.

        Args:
            request: The current request object.

        Returns:
            QuerySet: Optimized queryset with related order data and shop filtering.
        """
        return super().get_queryset(request).select_related('order')

    def filter_by_shops(self, queryset, shops):
        """
        Filter order items by shop names (items from orders in these shops).

        Args:
            queryset: The base queryset to filter.
            shops: List of shop names to filter by.

        Returns:
            QuerySet: Filtered queryset.
        """
        return queryset.filter(order__shop__in=shops)

    def object_belongs_to_user_shops(self, obj, user_shops):
        """
        Check if an order item belongs to the user's shops (item from order in user's shops).

        Args:
            obj: The OrderItem instance to check.
            user_shops: List of shop names the user has access to.

        Returns:
            bool: True if order item's order is in user's shops.
        """
        return obj.order and obj.order.shop in user_shops

    def order_link(self, obj):
        """
        Display clickable link to the associated order.

        Args:
            obj: The OrderItem instance.

        Returns:
            str: HTML link to the order or dash if no order.
        """
        if not obj.order:
            return "-"
        link = reverse("admin:LaundryApp_order_change", args=[obj.order.pk])
        return format_html(
            '<a class="text-primary-600 hover:text-primary-800 underline" href="{}">{}</a>',
            link, obj.order.uniquecode
        )
    order_link.short_description = 'Order'
    order_link.admin_order_field = 'order__uniquecode'

    def items_display(self, obj):
        """
        Display individual items with badges in list view.

        Shows first 3 items as badges, with a count of additional items if more exist.

        Args:
            obj: The OrderItem instance.

        Returns:
            str: HTML badges for items or dash if no items.
        """
        if not obj.itemname:
            return "-"

        items = [item.strip() for item in obj.itemname.split(',') if item.strip()]
        if not items:
            return "-"

        badges = []
        for item in items[:3]:  # Show first 3 items
            badges.append(
                f'<span class="px-2 py-1 bg-gray-100 text-gray-800 rounded-full text-xs font-medium">{item}</span>'
            )

        if len(items) > 3:
            badges.append(
                f'<span class="px-2 py-1 bg-blue-100 text-blue-800 rounded-full text-xs font-medium">+{len(items)-3} more</span>'
            )

        return format_html(' '.join(badges))
    items_display.short_description = 'Items'

    def items_list_display(self, obj):
        """
        Display all items in a readable list format for the detail view.

        Args:
            obj: The OrderItem instance.

        Returns:
            str: HTML unordered list of all items.
        """
        if not obj.itemname:
            return "-"

        items = [item.strip() for item in obj.itemname.split(',') if item.strip()]
        if not items:
            return "-"

        item_list = ''.join([f'<li class="py-1">{item}</li>' for item in items])
        return format_html(f'<ul class="list-disc list-inside">{item_list}</ul>')
    items_list_display.short_description = 'Items List'

    def total_item_price_formatted(self, obj):
        """
        Calculate and display total price for the order item.

        Args:
            obj: The OrderItem instance.

        Returns:
            str: Formatted total price.
        """
        total = (obj.unit_price or 0) * (obj.quantity or 0)
        return format_html('<span class="font-medium text-green-600">KSh {}</span>', f'{total:,.2f}')
    total_item_price_formatted.short_description = 'Total Price'

    def has_add_permission(self, request):
        """
        Disable adding OrderItems directly through admin.

        OrderItems should only be created through Order admin interface.

        Args:
            request: The current request object.

        Returns:
            bool: Always False to prevent direct creation.
        """
        return False

    # Customize the fields shown in the detail view
    fieldsets = (
        (None, {
            'fields': ('order', 'servicetype', 'itemtype', 'items_list_display', 'quantity', 'itemcondition', 'unit_price', 'total_item_price_formatted', 'additional_info')
        }),
    )