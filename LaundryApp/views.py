from decimal import Decimal, InvalidOperation
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django_daraja.mpesa.core import MpesaClient
import json
import logging
import datetime
from functools import wraps
from datetime import datetime

# Django imports
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.db.models import Q, Prefetch, Sum, Count, Avg, F, ExpressionWrapper, DecimalField, Value
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.contrib.auth.forms import AuthenticationForm

from django.db import IntegrityError, transaction
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth import get_user_model
from django.db.models.functions import Coalesce
from django.utils.timezone import now

# Local imports
from .models import (
    Customer, 
    Order, 
    OrderItem, 
    ExpenseField, 
    ExpenseRecord, 
    LaundryProfile,
)
from .forms import ( 
    CustomerForm, 
    OrderForm,
    OrderItemForm, 
    UserEditForm,
    UserCreateForm,
    ProfileEditForm, 
    ExpenseFieldForm,
    ExpenseRecordForm,
    LaundryProfileForm 
)
from HotelApp.models import HotelExpenseRecord
from .resource import OrderResource
from .analytics import DashboardAnalytics

# Setup logger
logger = logging.getLogger(__name__)
User = get_user_model()

# Constants
DEFAULT_PAGE_SIZE = 15
MAX_PAGE_SIZE = 100
EXPORT_FILENAME_PREFIX = "orders_export"
ALLOWED_EXPORT_FORMATS = ['csv', 'xlsx']
VALID_ORDER_STATUSES = ['pending', 'processing', 'Completed', 'Delivered_picked']
VALID_PAYMENT_STATUSES = ['pending', 'partial', 'completed']

class OrderManagerError(Exception):
    """Custom exception for order management operations"""
    pass

class PermissionDeniedError(OrderManagerError):
    """Raised when user doesn't have permission for an operation"""
    pass

class OrderNotFoundError(OrderManagerError):
    """Raised when order is not found"""
    pass

class InvalidDataError(OrderManagerError):
    """Raised when invalid data is provided"""
    pass

# Cached functions and reusable queries
def get_user_shops(request):
    """Get the shops associated with the current user based on profile"""
    if request.user.is_superuser:
        return None  # Superusers can access all shops
    
    try:
        # Check if user has a laundry profile with shop assignment
        if hasattr(request.user, 'laundry_profile') and request.user.laundry_profile.shop:
            # Return the shop as a list to maintain compatibility
            return [request.user.laundry_profile.shop.title()]
        return []  # If no shop is assigned, return empty list
    except Exception as e:
        logger.error(f"Error getting user shops for user {request.user.id}: {str(e)}")
        return []  # If any error occurs, return empty list

def apply_order_permissions(queryset, request):
    """Apply permission-based filtering to order queryset"""
    user_shops = get_user_shops(request)
    
    if user_shops is not None:  # Not superuser
        if user_shops:  # User has shop assignments
            # Use exact match since we normalized to title case
            queryset = queryset.filter(shop__in=user_shops)
        else:  # User has no shop assignments
            queryset = queryset.none()
    
    return queryset

def apply_customer_permissions(queryset, request):
    """Apply permission-based filtering to customer queryset"""
    user_shops = get_user_shops(request)
    
    if user_shops is not None:  # Not superuser
        if user_shops:  # User has shop assignments
            # Get customers who have orders in the user's shops
            customer_ids = Order.objects.filter(
                shop__in=user_shops
            ).values_list('customer_id', flat=True).distinct()
            queryset = queryset.filter(id__in=customer_ids)
        else:  # User has no shop assignments
            queryset = queryset.none()
    
    return queryset

def is_admin(user):
    """Check if user has admin privileges"""
    return user.is_superuser or getattr(user, 'user_type', None) == 'admin'

def is_staff(user):
    """Check if user has staff privileges"""
    return user.is_staff or getattr(user, 'user_type', None) in ['admin', 'staff']

# Decorators for permission checking
def shop_required(view_func):
    """Decorator to ensure user has a shop assignment"""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        user_shops = get_user_shops(request)
        if not user_shops and not request.user.is_superuser:
            messages.error(request, "You don't have permission to access this page.")
            return redirect('dashboard')
        return view_func(request, *args, **kwargs)
    return _wrapped_view

def admin_required(view_func):
    """Decorator to ensure user is an admin"""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not is_admin(request.user):
            messages.error(request, "You don't have admin privileges.")
            return redirect('laundry:dashboard')
        return view_func(request, *args, **kwargs)
    return _wrapped_view

def staff_required(view_func):
    """Decorator to ensure user is staff"""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not is_staff(request.user):
            messages.error(request, "You don't have staff privileges.")
            return redirect('laundry:Laundrydashboard')
        return view_func(request, *args, **kwargs)
    return _wrapped_view

def get_base_order_queryset():
    """Base queryset for orders with common prefetching"""
    return Order.objects.select_related('customer').prefetch_related(
        Prefetch('items', queryset=OrderItem.objects.only(
            'servicetype', 'itemname', 'quantity', 'itemtype', 
            'itemcondition', 'total_item_price', 'unit_price'
        ))
    ).only(
        'id', 'uniquecode', 'order_status', 'payment_status', 'payment_type',
        'shop', 'delivery_date', 'amount_paid', 'balance', 'total_price', 
        'created_at', 'customer__name', 'customer__phone', 'customer__address', 
        'addressdetails'
    )

def check_order_permission(request, order):
    """Check if user has permission to access this order"""
    user_shops = get_user_shops(request)
    
    if user_shops is not None and user_shops:  # Not superuser
        if order.shop not in user_shops:
            return False
    
    return True

def check_customer_permission(request, customer):
    """Check if user has permission to access this customer"""
    user_shops = get_user_shops(request)
    
    if user_shops is not None and user_shops:  # Not superuser
        # Check if customer has orders in user's shops
        customer_shop_orders = Order.objects.filter(
            customer=customer,
            shop__in=user_shops
        ).exists()
        if not customer_shop_orders:
            return False
    
    return True

def validate_order_status(status):
    """Validate order status"""
    if status not in VALID_ORDER_STATUSES:
        raise InvalidDataError(f"Invalid order status: {status}")

def validate_payment_status(status):
    """Validate payment status"""
    if status not in VALID_PAYMENT_STATUSES:
        raise InvalidDataError(f"Invalid payment status: {status}")

def safe_decimal_conversion(value, field_name="amount"):
    """Safely convert value to Decimal with proper error handling"""
    if value is None:
        return Decimal('0.00')
    
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as e:
        logger.error(f"Invalid decimal value for {field_name}: {value}")
        raise InvalidDataError(f"Invalid {field_name} format: {value}")

def get_page_obj(paginator, page_number):
    """Handle pagination safely"""
    try:
        return paginator.page(page_number)
    except PageNotAnInteger:
        return paginator.page(1)
    except EmptyPage:
        return paginator.page(paginator.num_pages)

def get_order_stats(orders):
    """Get order statistics in optimized way"""
    try:
        status_counts = orders.aggregate(
            total=Count('id'),
            pending=Count('id', filter=Q(order_status='pending')),
            completed=Count('id', filter=Q(order_status='Completed')),
            delivered=Count('id', filter=Q(order_status='Delivered_picked')),
            in_progress=Count('id', filter=Q(order_status='in_progress'))
        )
        
        return {
            'total_orders': status_counts['total'] or 0,
            'pending_orders': status_counts['pending'] or 0,
            'completed_orders': status_counts['completed'] or 0,
            'delivered_orders': status_counts['delivered'] or 0,
            'in_progress_orders': status_counts['in_progress'] or 0,
        }
    except Exception as e:
        logger.error(f"Error calculating order stats: {str(e)}")
        return {
            'total_orders': 0,
            'pending_orders': 0,
            'completed_orders': 0,
            'delivered_orders': 0,
            'in_progress_orders': 0,
        }

def handle_export(orders, export_format):
    """Handle export functionality with validation"""
    if export_format not in ALLOWED_EXPORT_FORMATS:
        raise InvalidDataError(f"Invalid export format: {export_format}")
    
    try:
        dataset = OrderResource().export(queryset=orders)
        timestamp = timezone.now().strftime('%Y-%m-%d_%H-%M-%S')
        
        if export_format == 'csv':
            response = HttpResponse(dataset.csv, content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename="{EXPORT_FILENAME_PREFIX}_{timestamp}.csv"'
            return response
            
        elif export_format == 'xlsx':
            xlsx_data = dataset.export('xlsx')
            response = HttpResponse(
                xlsx_data, 
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
            response['Content-Disposition'] = f'attachment; filename="{EXPORT_FILENAME_PREFIX}_{timestamp}.xlsx"'
            return response
    except Exception as e:
        logger.error(f"Error during export: {str(e)}")
        raise OrderManagerError(f"Export failed: {str(e)}")

def serialize_order_for_json(order):
    """Serialize order data for JSON response"""
    try:
        customer_phone = str(order.customer.phone) if order.customer.phone else ''
        
        order_data = {
            'id': order.id,
            'uniquecode': order.uniquecode,
            'customer': {
                'name': order.customer.name,
                'phone': customer_phone,
                'address': order.customer.address or '',
            },
            'items': [],
            'amount_paid': float(order.amount_paid or 0),
            'balance': float(order.balance or 0),
            'total_price': float(order.total_price or 0),
            'order_status': order.order_status,
            'payment_status': order.payment_status,
            'created_at': order.created_at.strftime('%Y-%m-%d %H:%M') if order.created_at else '',
        }

        # Serialize items
        for item in order.items.all():
            order_data['items'].append({
                'servicetype': item.servicetype or '',
                'itemtype': item.itemtype or '',
                'itemname': item.itemname or '',
                'itemcondition': item.itemcondition or '',
                'unit_price': float(item.unit_price or 0),
                'quantity': item.quantity or 1,
                'total_item_price': float(item.total_item_price or 0),
            })

        return order_data
    except Exception as e:
        logger.error(f"Error serializing order {order.id}: {str(e)}")
        raise OrderManagerError(f"Failed to serialize order data: {str(e)}")

def validate_date_range(from_date_str, to_date_str):
    """Validate and parse date range parameters"""
    from_date = None
    to_date = None
    
    try:
        if from_date_str:
            from_date = datetime.strptime(from_date_str, "%Y-%m-%d").date()
        if to_date_str:
            to_date = datetime.strptime(to_date_str, "%Y-%m-%d").date()
            
        # Validate date range logic
        if from_date and to_date and from_date > to_date:
            raise InvalidDataError("From date cannot be after to date")
            
    except ValueError as e:
        raise InvalidDataError(f"Invalid date format: {str(e)}")
    
    return from_date, to_date

# Views
@login_required
@admin_required
def dashboard_view(request):
    """Dashboard view with analytics and reporting"""
    try:
        current_year = timezone.now().year
        
        # Validate and parse parameters
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

        # Handle date range
        from_date_str = request.GET.get('from_date')
        to_date_str = request.GET.get('to_date')
        from_date, to_date = validate_date_range(from_date_str, to_date_str)

        # Get analytics data
        class MockAdmin:
            def get_user_shops(self, request):
                return get_user_shops(request)
        
        mock_admin = MockAdmin()
        analytics = DashboardAnalytics(mock_admin)
        
        data = analytics.get_dashboard_data(request, selected_year, selected_month, from_date, to_date)
        context = analytics.prepare_dashboard_context(request, data, selected_year, selected_month, from_date, to_date)
        
        context.update({
            'selected_year': selected_year,
            'selected_month': selected_month,
            'from_date': from_date,
            'to_date': to_date,
        })
        
        return render(request, 'Admin/reports.html', context)
        
    except Exception as e:
        logger.error(f"Error in dashboard view: {str(e)}")
        messages.error(request, "An error occurred while loading the dashboard.")
        return render(request, 'Admin/reports.html', {
            'selected_year': timezone.now().year,
            'selected_month': None,
            'from_date': None,
            'to_date': None,
        })


@login_required
@shop_required
def customordertable(request):
    """Order table view with AJAX support"""
    # Check if it's an AJAX request
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return handle_ajax_request(request)
    
    # For initial page load, return basic context
    context = {
        'order_status_choices': Order.ORDER_STATUS_CHOICES,
        'payment_status_choices': Order.PAYMENT_STATUS_CHOICES,
        'today': timezone.now().date(),
    }
    
    # Add shop choices for superusers to enable filtering
    if request.user.is_superuser:
        context['shop_choices'] = Order.SHOP_CHOICE
    
    return render(request, 'Admin/orders_table.html', context)

def handle_ajax_request(request):
    """Handle AJAX requests for order data"""
    try:
        # Start with base queryset - include ALL orders (excluding Delivered_picked)
        orders = get_base_order_queryset().exclude(
            order_status__in=['Delivered_picked']
        ).exclude(
            Q(uniquecode__isnull=True) | Q(uniquecode='')
        )

        # Apply permission filtering
        orders = apply_order_permissions(orders, request)

        # Apply filters in a single optimized block
        filters = Q()
        
        # Payment status filter
        payment_filter = request.GET.get('payment_status', '')
        if payment_filter:
            validate_payment_status(payment_filter)
            filters &= Q(payment_status=payment_filter)

        # Search filter
        search_query = request.GET.get('search', '')
        if search_query:
            filters &= (
                Q(uniquecode__icontains=search_query) |
                Q(customer__name__icontains=search_query) |
                Q(customer__phone__icontains=search_query) |
                Q(items__servicetype__icontains=search_query) |
                Q(items__itemname__icontains=search_query)
            )
            
        # Shop filter - available for superusers
        shop_filter = request.GET.get('shop', '')
        if shop_filter and request.user.is_superuser:
            # Validate shop filter against available choices
            valid_shops = [choice[0] for choice in Order.SHOP_CHOICE]
            if shop_filter in valid_shops:
                filters &= Q(shop=shop_filter)

        if filters:
            orders = orders.filter(filters).distinct()

        # Handle export
        export_format = request.GET.get('export', '')
        if export_format:
            return handle_export(orders, export_format)

        # Order by creation date and paginate
        orders = orders.order_by('-created_at')

        # Get counts for stats cards before pagination
        stats = get_order_stats(orders)

        # Pagination
        paginator = Paginator(orders, DEFAULT_PAGE_SIZE)
        page_number = request.GET.get('page')
        page_obj = get_page_obj(paginator, page_number)

        # Prepare data for AJAX response
        data = {
            'success': True,
            'orders': [serialize_order_for_json(order) for order in page_obj],
            'stats': stats,
            'pagination': {
                'has_other_pages': page_obj.has_other_pages(),
                'has_previous': page_obj.has_previous(),
                'has_next': page_obj.has_next(),
                'number': page_number,
                'num_pages': page_obj.paginator.num_pages,
                'start_index': page_obj.start_index(),
                'end_index': page_obj.end_index(),
                'count': page_obj.paginator.count,
            }
        }
        
        # Add shop choices for superusers in AJAX response
        if request.user.is_superuser:
            data['shop_choices'] = Order.SHOP_CHOICE

        return JsonResponse(data)
    
    except InvalidDataError as e:
        logger.warning(f"Invalid data in AJAX request: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e),
            'message': 'Invalid request parameters'
        }, status=400)
    except OrderManagerError as e:
        logger.error(f"Order manager error in AJAX request: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e),
            'message': 'An error occurred while processing your request'
        }, status=500)
    except Exception as e:
        logger.error(f"Unexpected error in AJAX request: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': 'Internal server error',
            'message': 'An unexpected error occurred'
        }, status=500)



@login_required
@shop_required
def update_order_status_ajax(request, order_id, status):
    """Update order status via AJAX"""
    try:
        validate_order_status(status)
        
        order = Order.objects.get(id=order_id)
        
        # Check if user has permission to update this order
        if not check_order_permission(request, order):
            raise PermissionDeniedError("You don't have permission to update this order.")
        
        order.order_status = status
        order.save()
        
        logger.info(f"Order {order.uniquecode} status updated to {status} by user {request.user.id}")
        
        return JsonResponse({
            'success': True,
            'message': f'Order status updated to {status}'
        })
        
    except Order.DoesNotExist:
        logger.warning(f"Order not found: {order_id}")
        return JsonResponse({
            'success': False,
            'message': 'Order not found'
        }, status=404)
    except (PermissionDeniedError, InvalidDataError) as e:
        logger.warning(f"Permission or validation error: {str(e)}")
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=403)
    except Exception as e:
        logger.error(f"Error updating order status: {str(e)}")
        return JsonResponse({
            'success': False,
            'message': 'An error occurred while updating the order'
        }, status=500)

@login_required
@shop_required
def order_detail(request, order_id):
    """Get order details for AJAX modal"""
    try:
        order = get_base_order_queryset().get(id=order_id)
        
        # Check if user has permission to view this order
        if not check_order_permission(request, order):
            raise PermissionDeniedError("You don't have permission to view this order.")
        
        order_data = serialize_order_for_json(order)
        
        return JsonResponse({
            'success': True,
            'order': order_data
        })
        
    except Order.DoesNotExist:
        logger.warning(f"Order not found: {order_id}")
        return JsonResponse({
            'success': False,
            'message': "Order not found."
        }, status=404)
    except PermissionDeniedError as e:
        logger.warning(f"Permission denied for order {order_id}: {str(e)}")
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=403)
    except Exception as e:
        logger.error(f"Error fetching order details for order {order_id}: {str(e)}")
        return JsonResponse({
            'success': False,
            'message': "An error occurred while fetching order details."
        }, status=500)

@login_required
@shop_required
@transaction.atomic
def order_edit(request):
    """Update order via AJAX with transaction safety"""
    # Check if it's an AJAX request
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'
    
    if request.method != 'POST' or not is_ajax:
        return JsonResponse({
            'success': False,
            'message': "Invalid request method or not an AJAX request."
        }, status=400)

    try:
        order_id = request.POST.get('order_id')
        if not order_id:
            raise InvalidDataError("Order ID is required.")

        order = Order.objects.get(id=order_id)
        
        # Check if user has permission to update this order
        if not check_order_permission(request, order):
            raise PermissionDeniedError("You don't have permission to update this order.")
        
        # Update customer information
        customer = order.customer
        customer.name = request.POST.get('name', customer.name)
        
        # Handle phone number
        phone = request.POST.get('phone')
        if phone:
            customer.phone = phone
        
        customer.save()
        
        # Update order information
        order_status = request.POST.get('order_status')
        if order_status:
            validate_order_status(order_status)
            order.order_status = order_status
            
        payment_status = request.POST.get('payment_status')
        if payment_status:
            validate_payment_status(payment_status)
            order.payment_status = payment_status
        
        # Update amount paid and recalculate balance
        amount_paid = request.POST.get('amount_paid')
        if amount_paid is not None:
            order.amount_paid = safe_decimal_conversion(amount_paid, "amount_paid")
            if order.amount_paid < 0:
                raise InvalidDataError("Amount paid cannot be negative.")
            if order.amount_paid > order.total_price:
                order.amount_paid = order.total_price
            order.balance = order.total_price - order.amount_paid
        
        # Handle order items
        items_to_keep = []
        item_count = 0
        
        # Process existing items
        for item in order.items.all():
            item_name = request.POST.get(f'items-{item_count}-itemname')
            service_type = request.POST.get(f'items-{item_count}-servicetype')
            unit_price = request.POST.get(f'items-{item_count}-unit_price')
            
            if item_name and service_type and unit_price:
                # Update existing item
                item.itemname = item_name
                item.servicetype = service_type
                item.unit_price = safe_decimal_conversion(unit_price, "unit_price")
                
                # Calculate total item price
                item.total_item_price = item.unit_price * (item.quantity or 1)
                item.save()
                items_to_keep.append(item.id)
                item_count += 1
            else:
                # Delete item if fields are empty
                item.delete()
        
        # Add new items
        while f'items-{item_count}-itemname' in request.POST:
            item_name = request.POST.get(f'items-{item_count}-itemname')
            service_type = request.POST.get(f'items-{item_count}-servicetype')
            unit_price = request.POST.get(f'items-{item_count}-unit_price')
            
            if item_name and service_type and unit_price:
                unit_price_decimal = safe_decimal_conversion(unit_price, "unit_price")
                
                new_item = OrderItem.objects.create(
                    order=order,
                    itemname=item_name,
                    servicetype=service_type,
                    unit_price=unit_price_decimal,
                    quantity=1,  # Default quantity
                    total_item_price=unit_price_decimal
                )
                items_to_keep.append(new_item.id)
            
            item_count += 1
        
        # Recalculate total price
        total_price = sum(
            (item.total_item_price or Decimal('0.00'))
            for item in order.items.all()
        )
        order.total_price = total_price
        order.balance = total_price - (order.amount_paid or Decimal('0.00'))
        order.save()
        
        logger.info(f"Order {order.uniquecode} updated successfully by user {request.user.id}")
        
        return JsonResponse({
            'success': True,
            'message': f'Order {order.uniquecode} updated successfully!',
            'order_code': order.uniquecode
        })
        
    except Order.DoesNotExist:
        logger.warning(f"Order not found: {order_id}")
        return JsonResponse({
            'success': False,
            'message': "Order not found."
        }, status=404)
    except (PermissionDeniedError, InvalidDataError) as e:
        logger.warning(f"Permission or validation error: {str(e)}")
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=400)
    except Exception as e:
        logger.error(f"Error updating order: {str(e)}")
        return JsonResponse({
            'success': False,
            'message': "An error occurred while updating the order."
        }, status=500)

@login_required
@shop_required
def order_delete(request, order_code):
    """Delete an order via AJAX"""
    try:
        # Get the order
        order = Order.objects.only('uniquecode', 'shop').get(uniquecode=order_code)
        
        # Check if user has permission to delete this order
        if not check_order_permission(request, order):
            raise PermissionDeniedError("You don't have permission to delete this order.")
        
        if request.method == 'POST':
            order_code = order.uniquecode
            order.delete()
            
            logger.info(f"Order {order_code} deleted by user {request.user.id}")
            
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'message': f'Order {order_code} deleted successfully!'
                })
            else:
                messages.success(request, f'Order {order_code} deleted successfully!')
                return redirect('laundry:customordertable')
        
        # If it's a GET request and AJAX, return confirmation data
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'order': {
                    'uniquecode': order.uniquecode,
                    'customer_name': order.customer.name,
                },
                'message': f'Are you sure you want to delete order {order.uniquecode}?'
            })
        
        # Regular GET request - render confirmation page
        context = {'order': order}
        return render(request, 'Admin/order_confirm_delete.html', context)
        
    except Order.DoesNotExist:
        logger.warning(f"Order not found: {order_code}")
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'message': "Order not found."
            }, status=404)
        else:
            raise Http404("Order not found")
    except PermissionDeniedError as e:
        logger.warning(f"Permission denied for order deletion: {str(e)}")
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=403)
        else:
            messages.error(request, str(e))
            return redirect('laundry:customordertable')

@login_required
@shop_required
def update_payment_status(request, order_code):
    """Update payment status of an order"""
    try:
        # Load full order
        order = Order.objects.get(uniquecode=order_code)

        # Check if user has permission
        if not check_order_permission(request, order):
            raise PermissionDeniedError("You don't have permission to update this order.")

        if request.method != 'POST':
            return JsonResponse({
                'success': False,
                'message': 'Invalid request method.'
            }, status=405)

        payment_status = request.POST.get('payment_status')
        amount_paid_raw = request.POST.get('amount_paid', "0")

        if payment_status not in dict(Order.PAYMENT_STATUS_CHOICES):
            raise InvalidDataError('Invalid payment status.')

        order.payment_status = payment_status

        # Safely convert amount_paid
        amount_paid = safe_decimal_conversion(amount_paid_raw, "amount_paid")

        # Ensure amount_paid is not negative
        if amount_paid < 0:
            raise InvalidDataError('Amount paid cannot be negative.')

        # Ensure amount_paid does not exceed total
        if amount_paid > order.total_price:
            amount_paid = order.total_price

        order.amount_paid = amount_paid
        order.balance = order.total_price - amount_paid
        order.save()

        logger.info(f"Payment status updated for order {order_code} to {payment_status} by user {request.user.id}")

        return JsonResponse({
            'success': True,
            'message': f'Payment status updated to {payment_status}!',
            'order': {
                'uniquecode': order.uniquecode,
                'payment_status': order.payment_status,
                'amount_paid': str(order.amount_paid),
                'balance': str(order.balance),
                'total_price': str(order.total_price),
            }
        })

    except Order.DoesNotExist:
        logger.warning(f"Order not found: {order_code}")
        return JsonResponse({
            'success': False,
            'message': 'Order not found.'
        }, status=404)
    except (PermissionDeniedError, InvalidDataError) as e:
        logger.warning(f"Permission or validation error: {str(e)}")
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=400)
    except Exception as e:
        logger.error(f"Error updating payment status: {str(e)}")
        return JsonResponse({
            'success': False,
            'message': 'An error occurred while updating payment status.'
        }, status=500)

@login_required
@shop_required
@transaction.atomic
def createorder(request):
    """View to handle order creation with Django forms"""
    user_shops = get_user_shops(request)
    default_shop = user_shops[0] if user_shops else None

    if request.method == 'POST':
        try:
            post_data = request.POST.copy()

            # Force shop if user has only one
            if user_shops and len(user_shops) == 1:
                post_data['shop'] = user_shops[0]

            # Default order_status
            if not post_data.get('order_status'):
                post_data['order_status'] = 'pending'

            # Customer handling
            phone = post_data.get('phone', '').strip()
            customer_id = post_data.get('customer_id', '').strip()
            customer = None
            customer_exists = False

            if customer_id:
                try:
                    customer = Customer.objects.get(id=customer_id)
                    customer_exists = True
                    if customer.name != post_data.get('name', ''):
                        customer.name = post_data.get('name', '')
                        customer.save()
                except Customer.DoesNotExist:
                    customer_exists = False
            elif phone:
                try:
                    customer = Customer.objects.get(phone=phone)
                    customer_exists = True
                    if customer.name != post_data.get('name', ''):
                        customer.name = post_data.get('name', '')
                        customer.save()
                except Customer.DoesNotExist:
                    customer_exists = False

            if customer_exists:
                customer_form_is_valid = True
                customer_form = None
            else:
                customer_form = CustomerForm(post_data)
                customer_form_is_valid = customer_form.is_valid()

            # Order + Items
            order_form = OrderForm(post_data)
            OrderItemFormSet = forms.formset_factory(OrderItemForm, extra=0)
            item_formset = OrderItemFormSet(post_data, prefix='items')

            order_form_is_valid = order_form.is_valid()
            item_formset_is_valid = item_formset.is_valid()

            if all([customer_form_is_valid, order_form_is_valid, item_formset_is_valid]):
                if not customer_exists:
                    customer = customer_form.save()

                order = order_form.save(commit=False)
                order.customer = customer
                order.created_by = request.user
                if not order.order_status:
                    order.order_status = 'pending'
                order.total_price = 0
                order.balance = -order.amount_paid
                order.save()

                # Save items
                for form in item_formset:
                    if form.cleaned_data and not form.cleaned_data.get('DELETE', False):
                        order_item = form.save(commit=False)
                        order_item.order = order

                        if "servicetype" in form.cleaned_data:
                            services = form.cleaned_data["servicetype"]
                            if isinstance(services, list):
                                order_item.servicetype = services

                        if hasattr(order_item, 'quantity') and hasattr(order_item, 'unit_price'):
                            if hasattr(order_item, 'total_item_price'):
                                order_item.total_item_price = order_item.quantity * order_item.unit_price

                        order_item.save()

                # Update totals
                total_price = sum(
                    (item.total_item_price or item.unit_price)
                    for item in order.items.all()
                )
                order.total_price = total_price
                order.balance = total_price - (order.amount_paid or 0)
                order.save()

                messages.success(request, f'Order created successfully! Code: {order.uniquecode}')
                return redirect('laundry:customordertable')

            else:
                error_messages = []
                if customer_form and not customer_form_is_valid:
                    for field, errors in customer_form.errors.items():
                        for error in errors:
                            error_messages.append(f"Customer {field}: {error}")
                if not order_form_is_valid:
                    for field, errors in order_form.errors.items():
                        for error in errors:
                            error_messages.append(f"Order {field}: {error}")
                if not item_formset_is_valid:
                    for i, form in enumerate(item_formset):
                        for field, errors in form.errors.items():
                            for error in errors:
                                error_messages.append(f"Item {i+1} {field}: {error}")

                messages.error(request, 'Please correct errors: ' + '; '.join(error_messages))

        except IntegrityError as e:
            if 'uniquecode' in str(e):
                logger.error(f"Order creation error (unique code conflict): {str(e)}")
                messages.error(request, 'Could not create order due to system error. Please try again.')
            else:
                logger.error(f"Order creation error: {str(e)}")
                messages.error(request, f'Error creating order: {str(e)}')
        except Exception as e:
            logger.error(f"Order creation error: {str(e)}")
            messages.error(request, f'Error creating order: {str(e)}')

    else:  # GET
        customer_form = CustomerForm()
        order_form = OrderForm()
        if user_shops and len(user_shops) == 1:
            order_form.fields['shop'].initial = user_shops[0]
        order_form.fields['order_status'].initial = 'pending'
        OrderItemFormSet = forms.formset_factory(OrderItemForm, extra=1)
        item_formset = OrderItemFormSet(prefix='items')

    context = {
        'customer_form': customer_form,
        'order_form': order_form,
        'item_formset': item_formset,
        'user_has_single_shop': user_shops and len(user_shops) == 1,
        'user_shop': default_shop,
    }
    return render(request, 'Admin/order_form.html', context)

@login_required
def laundrydashboard(request):
    """Laundry dashboard view"""
    if not request.user.is_authenticated:
        return redirect('login')

    try:
        # Get user's shops
        user_shops = get_user_shops(request)

        # Base queryset - exclude delivered orders from counts
        if request.user.is_superuser:
            # Superuser sees all orders
            orders = Order.objects.all()
            # For counts, exclude delivered orders
            count_orders = Order.objects.exclude(order_status='Delivered_picked')
        elif user_shops:
            # Staff sees only their shop's orders
            orders = Order.objects.filter(shop__in=user_shops)
            # For counts, exclude delivered orders
            count_orders = Order.objects.filter(shop__in=user_shops).exclude(order_status='Delivered_picked')
        else:
            # Users with no shop assignments see nothing
            orders = Order.objects.none()
            count_orders = Order.objects.none()

        # Calculate overall stats using count_orders (which excludes delivered orders)
        total_orders = count_orders.count()
        pending_orders = count_orders.filter(order_status='pending').count()
        completed_orders = count_orders.filter(order_status='Completed').count()

        # Get recent orders (including delivered)
        recent_orders = orders.select_related('customer').order_by('-created_at')[:10]

        # Shop-specific data for superuser
        shop_performance = None
        
        if request.user.is_superuser:
            # Get shop performance data for all shops
            shop_performance = {}
            shops = Order.objects.values_list('shop', flat=True).distinct()
            for shop in shops:
                if shop:  # Ensure shop is not empty
                    shop_orders = Order.objects.filter(shop=shop).exclude(order_status='Delivered_picked')
                    shop_performance[shop] = {
                        'total_orders': shop_orders.count(),
                        'completed_orders': shop_orders.filter(order_status='Completed').count(),
                        'pending_orders': shop_orders.filter(order_status='pending').count(),
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
        }
        return render(request, 'Admin/dashboard.html', context)
        
    except Exception as e:
        logger.error(f"Error in laundry dashboard: {str(e)}")
        messages.error(request, "An error occurred while loading the dashboard.")
        return render(request, 'Admin/dashboard.html', {
            'user_shops': [],
            'total_orders': 0,
            'pending_orders': 0,
            'completed_orders': 0,
            'recent_orders': [],
            'shop_performance': None,
        })

def get_laundry_profit_and_hotel(request):
    """
    Display current month data by default without user selection
    """
    if not request.user.is_authenticated or not request.user.is_superuser:
        return redirect('login')

    try:
        current_date = now()
        current_year = current_date.year
        current_month = current_date.month
        
        # Convert month number to month name for display
        month_names = {
            1: 'January', 2: 'February', 3: 'March', 4: 'April',
            5: 'May', 6: 'June', 7: 'July', 8: 'August',
            9: 'September', 10: 'October', 11: 'November', 12: 'December'
        }
        current_month_name = month_names.get(current_month, 'Unknown')
        
        # Create a simple admin instance wrapper
        class SimpleAdmin:
            def get_user_shops(self, request):
                # For superusers, return None to show all shops
                if request.user.is_superuser:
                    return None
                # Add your shop logic here for non-superusers
                return ['Shop A', 'Shop B']
        
        # Initialize DashboardAnalytics with the simple admin
        analytics = DashboardAnalytics(SimpleAdmin())
        
        # Get comprehensive dashboard data for the current month
        dashboard_data = analytics.get_dashboard_data(
            request=request,
            selected_year=current_year,
            selected_month=current_month,  # Get current month data
            from_date=None,
            to_date=None,
            payment_status=None,
            shop=None
        )
        
        # Extract data from dashboard_data with fallbacks
        order_stats = dashboard_data.get('order_stats', {})
        expense_stats = dashboard_data.get('expense_stats', {})
        hotel_stats = dashboard_data.get('hotel_stats', {})
        business_growth = dashboard_data.get('business_growth', {})
        
        laundry_revenue = order_stats.get('total_revenue', 0)
        laundry_expenses = expense_stats.get('total_expenses', 0)
        laundry_profit = laundry_revenue - laundry_expenses
        
        hotel_revenue = hotel_stats.get('total_revenue', 0)
        hotel_expenses = hotel_stats.get('total_expenses', 0)
        hotel_profit = hotel_stats.get('net_profit', 0)
        
        total_revenue = business_growth.get('total_revenue', laundry_revenue + hotel_revenue)
        total_profit = business_growth.get('net_profit', laundry_profit + hotel_profit)
        
        # Prepare context
        context = {
            'total_revenue': float(total_revenue),
            'laundry_revenue': float(laundry_revenue),
            'laundry_expenses': float(laundry_expenses),
            'laundry_profit': float(laundry_profit),
            'hotel_revenue': float(hotel_revenue),
            'hotel_expenses': float(hotel_expenses),
            'hotel_profit': float(hotel_profit),
            'total_profit': float(total_profit),
            'current_year': current_year,
            'current_month': current_month,
            'current_month_name': current_month_name,
            'dashboard_title': f"{current_month_name} {current_year} Dashboard"
        }
        
        return render(request, 'Admin/Generaldashboard.html', context)
        
    except Exception as e:
        logger.error(f"Error in get_laundry_profit_and_hotel: {e}")
        
        # Convert month number to month name for error case too
        month_names = {
            1: 'January', 2: 'February', 3: 'March', 4: 'April',
            5: 'May', 6: 'June', 7: 'July', 8: 'August',
            9: 'September', 10: 'October', 11: 'November', 12: 'December'
        }
        current_month_name = month_names.get(current_date.month, 'Unknown')
        
        return render(request, 'Admin/Generaldashboard.html', {
            'total_revenue': 0.0, 'laundry_revenue': 0.0, 'laundry_expenses': 0.0,
            'laundry_profit': 0.0, 'hotel_revenue': 0.0, 'hotel_expenses': 0.0,
            'hotel_profit': 0.0, 'total_profit': 0.0, 
            'current_year': current_date.year,
            'current_month': current_date.month,
            'current_month_name': current_month_name,
            'dashboard_title': f"{current_month_name} {current_date.year} Dashboard"
        })
def logout_view(request):
    """Log out the current user and redirect to login page"""
    try:
        auth_logout(request)
        messages.info(request, "You have been successfully logged out.")
    except Exception as e:
        logger.error(f"Error during logout: {str(e)}")
        messages.error(request, "An error occurred during logout.")
    
    return redirect('login')