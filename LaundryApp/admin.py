import logging
import json
from functools import wraps
from datetime import datetime

# Django imports
from django import forms
from django.contrib import admin, messages
from django.contrib.admin import register
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group, User
from django.http import Http404, HttpResponseRedirect, JsonResponse
from django.shortcuts import render, redirect
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.timezone import now
from django.views.decorators.cache import cache_page
from django.db.models import Q, Count, DecimalField, Max, Sum, Prefetch, Value
from django.db.models.functions import Coalesce
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.forms import formset_factory, inlineformset_factory


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
from .forms import CustomerForm, OrderForm, OrderItemForm

# Setup logger
logger = logging.getLogger(__name__)

# Constants
SHOP_A = 'Shop A'
SHOP_B = 'Shop B'
APP_LABEL = 'LaundryApp'

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


def create_laundry_order(customer_name, customer_phone, shop, delivery_date, order_items,
                        payment_type='pending_payment', payment_status='pending',
                        order_status='pending', address='', addressdetails='', created_by=None):
    """Create a new laundry order with customer and order items"""
    from django.db import transaction

    with transaction.atomic():
        # Get or create customer
        customer, created = Customer.objects.get_or_create(
            phone=customer_phone,
            defaults={
                'name': customer_name,
                'created_by': created_by
            }
        )

        # Create order
        order = Order.objects.create(
            customer=customer,
            shop=shop,
            delivery_date=delivery_date,
            payment_type=payment_type,
            payment_status=payment_status,
            order_status=order_status,
            address=address,
            addressdetails=addressdetails
        )

        # Create order items
        for item_data in order_items:
            OrderItem.objects.create(
                order=order,
                servicetype=item_data.get('servicetype', 'Washing'),
                itemtype=item_data.get('itemtype', 'Clothing'),
                itemname=item_data.get('itemname', ''),
                quantity=item_data.get('quantity', 1),
                itemcondition=item_data.get('itemcondition', 'new'),
                unit_price=item_data.get('unit_price', 0),
                additional_info=item_data.get('additional_info', '')
            )

        return order


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
        return f'{APP_LABEL}.{action}_{self.model_name}'

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

        if SHOP_A in user_groups:
            shops.append(SHOP_A)
        if SHOP_B in user_groups:
            shops.append(SHOP_B)

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
    list_display = ('name', 'phone', 'order_count')
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

    @permission_required(f'{APP_LABEL}.delete_customer')
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


# --- Payment Admin ---
@admin.register(Payment)
class PaymentAdmin(ShopPermissionMixin, AppPermissionMixin, ModelAdmin):
    """Admin interface for Payment model."""
    
    model_name = "payment"
    list_display = ('order_link', 'price')
    list_display_links = ('order_link', 'price')
    search_fields = ('order__uniquecode',)
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


class OrderAdminBase(ShopPermissionMixin, AppPermissionMixin, ModelAdmin, ImportExportModelAdmin):
    """Base class for Order admin functionality."""
    
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

    @permission_required(f'{APP_LABEL}.change_order')
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

    @permission_required(f'{APP_LABEL}.change_order')
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

    @permission_required(f'{APP_LABEL}.delete_order')
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


@admin.register(Order)
class OrderAdmin(OrderAdminBase):
    """Comprehensive admin interface for Order model."""
    
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('dashboard/', self.admin_site.admin_view(cache_page(60 * 5)(self.dashboard_view)),
                 name='laundryapp_dashboard'),
            path('', self.admin_site.admin_view(self.generaldashboard),
                 name='index'),
            path('Tables/', self.admin_site.admin_view(self.customordertable),
                  name='customordertable'),
            path('createorder/', self.admin_site.admin_view(self.createorder),
                
                name='createorder'),

            path('create-order-api/', self.admin_site.admin_view(self.create_order_api), name='create_order_api'),
            path('check-customer/',self.admin_site.admin_view(self.check_customer), name='check_customer')

        ]
        return custom_urls + urls

    def get_user_shops(self, request):
        """Get the shops associated with the current user based on group membership"""
        if request.user.is_superuser:
            return None  # Superusers can access all shops

        user_groups = request.user.groups.values_list('name', flat=True)
        shops = []

        if SHOP_A in user_groups:
            shops.append(SHOP_A)
        if SHOP_B in user_groups:
            shops.append(SHOP_B)

        return shops if shops else []

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

        return render(request, 'Admin/reports.html', context)

    def customordertable(self, request):
        # Start with base queryset - exclude delivered orders from the main query
        orders = Order.objects.select_related('customer').prefetch_related(
            Prefetch('items', queryset=OrderItem.objects.only(
                'servicetype', 'itemname', 'quantity', 'itemtype', 
                'itemcondition', 'total_item_price'
            ))
        ).only(
            'uniquecode', 'order_status', 'payment_status', 'payment_type',
            'shop', 'delivery_date', 'total_price', 'created_at', 
            'customer__name', 'customer__phone', 'address', 'addressdetails'
        ).exclude(order_status='delivered')  # Exclude delivered orders

        # Apply shop filtering based on user group
        user_shops = self.get_user_shops(request)
        if user_shops is not None:  # Not superuser
            if user_shops:  # User has shop assignments
                orders = orders.filter(shop__in=user_shops)
            else:  # User has no shop assignments
                orders = orders.none()

        # Apply status filters
        status_filter = request.GET.get('status', '')
        if status_filter:
            orders = orders.filter(order_status=status_filter)
            

        # Apply payment status filters
        payment_filter = request.GET.get('payment', '')
        if payment_filter:
            orders = orders.filter(payment_status=payment_filter)

        # Apply search filter
        search_query = request.GET.get('search', '')
        if search_query:
            orders = orders.filter(
                Q(uniquecode__icontains=search_query) |
                Q(customer__name__icontains=search_query) |
                Q(customer__phone__icontains=search_query) |
                Q(items__servicetype__icontains=search_query) |
                Q(items__itemname__icontains=search_query) |
                Q(address__icontains=search_query)
            ).distinct()

        # Order by creation date
        orders = orders.order_by('-created_at')

        # Pagination
        paginator = Paginator(orders, 25)  # Show 25 orders per page
        page_number = request.GET.get('page')
        try:
            page_obj = paginator.page(page_number)
        except PageNotAnInteger:
            page_obj = paginator.page(1)
        except EmptyPage:
            page_obj = paginator.page(paginator.num_pages)

        # Get counts for stats cards - exclude delivered orders from all counts
        total_orders = orders.count()
        pending_orders = orders.filter(order_status='pending').count()
        completed_orders = orders.filter(order_status='Completed').count()

        # Get status choices for filters
        order_status_choices = Order.ORDER_STATUS_CHOICES
        payment_status_choices = Order.PAYMENT_STATUS_CHOICES

        context = {
            'orders': page_obj,
            'total_orders': total_orders,
            'pending_orders': pending_orders,
            'completed_orders': completed_orders,
            'order_status_choices': order_status_choices,
            'payment_status_choices': payment_status_choices,
            'today': timezone.now().date(),
        }
        return render(request, 'Admin/orders_table.html', context)

    @method_decorator(csrf_exempt, name='dispatch')
    @method_decorator(require_POST, name='dispatch')
    def create_order_api(self, request):
        """API endpoint to create a new order"""
        try:
            data = json.loads(request.body)
            
            # Extract data from request
            customer_data = data.get('customer', {})
            order_data = data.get('order', {})
            items_data = data.get('items', [])
            
            # Get or create customer
            phone = customer_data.get('phone', '')
            name = customer_data.get('name', '')
            
            if not phone:
                return JsonResponse({
                    'success': False,
                    'message': 'Phone number is required'
                }, status=400)
            
            customer, created = Customer.objects.get_or_create(
                phone=phone,
                defaults={'name': name}
            )
            
            # Update customer name if it's different
            if not created and customer.name != name:
                customer.name = name
                customer.save()
            
            # Create order with proper defaults
            order = Order.objects.create(
                customer=customer,
                shop=order_data.get('shop'),
                delivery_date=order_data.get('delivery_date'),
                payment_type=order_data.get('payment_type', 'pending_payment'),
                payment_status=order_data.get('payment_status', 'pending'),
                order_status=order_data.get('order_status', 'pending'),  # Ensure default
                address=order_data.get('address', ''),
                addressdetails=order_data.get('addressdetails', ''),
                created_by=request.user if request.user.is_authenticated else None
            )
            
            # Create order items
            for item_data in items_data:
                OrderItem.objects.create(
                    order=order,
                    servicetype=item_data.get('servicetype', 'Washing'),
                    itemtype=item_data.get('itemtype', 'Clothing'),
                    itemname=item_data.get('itemname', ''),
                    quantity=item_data.get('quantity', 1),
                    itemcondition=item_data.get('itemcondition', 'new'),
                    unit_price=item_data.get('unit_price', 0),
                    additional_info=item_data.get('additional_info', '')
                )
            
            # Calculate total price
            order.calculate_total_price()
            order.save()
            
            return JsonResponse({
                'success': True,
                'order_code': order.uniquecode,
                'total_price': float(order.total_price),
                'message': 'Order created successfully'
            })
            
        except Exception as e:
            logger.error(f"API Order creation error: {str(e)}")
            return JsonResponse({
                'success': False,
                'message': f'Error creating order: {str(e)}'
            }, status=400)

    def createorder(self, request):
        """View to handle order creation with Django forms"""
        # Get user's shop based on group membership
        user_shops = self.get_user_shops(request)
        default_shop = user_shops[0] if user_shops else ''
        
        if request.method == 'POST':
            # Create a mutable copy of the POST data
            post_data = request.POST.copy()
            
            # For users with only one shop, override the shop value
            if user_shops and len(user_shops) == 1:
                post_data['shop'] = user_shops[0]
            
            # Ensure order_status is set to 'pending' if not provided
            if 'order_status' not in post_data or not post_data['order_status']:
                post_data['order_status'] = 'pending'
            
            # Check if customer already exists FIRST
            phone = post_data.get('phone', '')
            customer = None
            customer_exists = False
            
            if phone:
                try:
                    customer = Customer.objects.get(phone=phone)
                    customer_exists = True
                    # If customer exists, we'll bypass the customer form validation completely
                except Customer.DoesNotExist:
                    customer_exists = False
            
            # Only validate customer form if customer doesn't exist
            if customer_exists:
                # Customer exists - create a minimal valid form
                customer_form = CustomerForm({'name': post_data.get('name', ''), 'phone': phone})
                customer_form_is_valid = True  # Bypass validation for existing customers
            else:
                # Customer doesn't exist - validate the form normally
                customer_form = CustomerForm(post_data)
                customer_form_is_valid = customer_form.is_valid()
            
            # Validate order form and item formset
            order_form = OrderForm(post_data)
            OrderItemFormSet = formset_factory(OrderItemForm, extra=0)
            item_formset = OrderItemFormSet(post_data, prefix='items')
            
            order_form_is_valid = order_form.is_valid()
            item_formset_is_valid = item_formset.is_valid()
            
            if all([customer_form_is_valid, order_form_is_valid, item_formset_is_valid]):
                try:
                    # If customer exists, use the existing customer
                    if customer_exists:
                        # Update customer name if it's different
                        if customer.name != post_data.get('name', ''):
                            customer.name = post_data.get('name', '')
                            customer.save()
                    else:
                        # Save new customer
                        customer = customer_form.save()
                    
                    # Save order with customer reference
                    order = order_form.save(commit=False)
                    order.customer = customer
                    order.created_by = request.user
                    
                    # Ensure order status is set (double safety)
                    if not order.order_status:
                        order.order_status = 'pending'
                    
                    order.save()
                    
                    # Save order items
                    for form in item_formset:
                        if form.cleaned_data and not form.cleaned_data.get('DELETE', False):
                            order_item = form.save(commit=False)
                            order_item.order = order
                            order_item.save()
                    
                    # Recalculate total price
                    order.calculate_total_price()
                    order.save()
                    
                    messages.success(request, f'Order created successfully! Order code: {order.uniquecode}')
                    return redirect('admin:customordertable')
                    
                except Exception as e:
                    messages.error(request, f'Error creating order: {str(e)}')
                    # Log the error for debugging
                    logger.error(f"Order creation error: {str(e)}")
            else:
                # Collect all form errors
                error_messages = []
                if not customer_form_is_valid:
                    for field, errors in customer_form.errors.items():
                        for error in errors:
                            error_messages.append(f"Customer {field}: {error}")
                
                if not order_form_is_valid:
                    for field, errors in order_form.errors.items():
                        for error in errors:
                            error_messages.append(f"Order {field}: {error}")
                
                if not item_formset_is_valid:
                    for i, form in enumerate(item_formset):
                        if not form.is_valid():
                            for field, errors in form.errors.items():
                                for error in errors:
                                    error_messages.append(f"Item {i+1} {field}: {error}")
                
                messages.error(request, 'Please correct the following errors: ' + '; '.join(error_messages))
        else:
            # GET request - initialize empty forms
            customer_form = CustomerForm()
            order_form = OrderForm()
            if user_shops and len(user_shops) == 1:
                order_form.fields['shop'].initial = user_shops[0]
            
            # Set default order status to 'pending'
            order_form.fields['order_status'].initial = 'pending'
            
            OrderItemFormSet = formset_factory(OrderItemForm, extra=1)
            item_formset = OrderItemFormSet(prefix='items')
        
        context = {
            'customer_form': customer_form,
            'order_form': order_form,
            'item_formset': item_formset,
            'user_has_single_shop': user_shops and len(user_shops) == 1,
            'user_shop': default_shop,
        }
        
        return render(request, 'Admin/order_form.html', context)

    def check_customer(self, request):
        """Check if a customer exists by phone number"""
        phone = request.GET.get('phone', '')
        if phone:
            try:
                customer = Customer.objects.get(phone=phone)
                return JsonResponse({
                    'exists': True,
                    'name': customer.name,
                    'phone': customer.phone
                })
            except Customer.DoesNotExist:
                return JsonResponse({'exists': False})
        return JsonResponse({'exists': False})
    def generaldashboard(self, request):
        if not request.user.is_authenticated:
            return redirect('admin:login')

        # Get user's shops
        user_shops = self.get_user_shops(request)

        # Base queryset - exclude delivered orders from counts
        if request.user.is_superuser:
            # Superuser sees all orders
            orders = Order.objects.all()
            # For counts, exclude delivered orders
            count_orders = Order.objects.exclude(order_status='Delivered')
        elif user_shops:
            # Staff sees only their shop's orders
            orders = Order.objects.filter(shop__in=user_shops)
            # For counts, exclude delivered orders
            count_orders = Order.objects.filter(shop__in=user_shops).exclude(order_status='Delivered')
        else:
            # Users with no shop assignments see nothing
            orders = Order.objects.none()
            count_orders = Order.objects.none()

        # Calculate stats using count_orders (which excludes delivered orders)
        total_orders = count_orders.count()
        pending_orders = count_orders.filter(order_status='Pending').count()
        completed_orders = count_orders.filter(order_status='Completed').count()

        # Get recent orders (including delivered)
        recent_orders = orders.select_related('customer').order_by('-created_at')[:10]

        # For superusers, get shop performance data (excluding delivered orders)
        shop_performance = None
        if request.user.is_superuser:
            shop_performance = {}
            shops = Order.objects.values_list('shop', flat=True).distinct()
            for shop in shops:
                if shop:  # Ensure shop is not empty
                    shop_orders = Order.objects.filter(shop=shop).exclude(order_status='Delivered')
                    shop_performance[shop] = {
                        'total_orders': shop_orders.count(),
                        'completed_orders': shop_orders.filter(order_status='Completed').count(),
                        'total_revenue': shop_orders.aggregate(
                            total=Sum('total_price')
                        )['total'] or 0
                    }

        context = {
            'user_shops': user_shops,
            'total_orders': total_orders,
            'pending_orders': pending_orders,
            'completed_orders': completed_orders,
            'recent_orders': recent_orders,
            'shop_performance': shop_performance,
            **self.admin_site.each_context(request),
        }
        return render(request, 'Admin/dashboard.html', context)