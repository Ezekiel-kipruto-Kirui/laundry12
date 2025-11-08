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
from django.views.decorators.csrf import csrf_exempt, csrf_protect
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

from LaundryApp.resource import OrderResource

# Local imports
from .models import (
    Customer, 
    Order, 
    OrderItem, 
    ExpenseField, 
    ExpenseRecord, 
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
)

from .View.analytics import DashboardAnalytics
# laundry/LaundryApp/views.py
from rest_framework import status, generics
from rest_framework.response import Response
from rest_framework.decorators import api_view

from .serializers import CustomerSerializer, OrderSerializer
# tyty=0721422637
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from rest_framework.response import Response
from .models import Customer
from .serializers import CustomerSerializer
logger = logging.getLogger(__name__)
User = get_user_model()
@api_view(['POST'])
@permission_classes([IsAuthenticated])  # ✅ Require login
def check_or_create_customer(request):
    phone = request.data.get('phone')
    name = request.data.get('name')
    

    if not phone:
        return Response({"error": "Phone is required"}, status=status.HTTP_400_BAD_REQUEST)

    # ✅ Check if customer exists
    customer = Customer.objects.filter(phone=phone).first()

    if customer:
        serializer = CustomerSerializer(customer)
        return Response({
            "exists": True,
            "message": "Customer already exists.",
            "customer": serializer.data
        })

    # ✅ If not exists, create and attach the logged-in user
    serializer = CustomerSerializer(data={
        "name": name,
        "phone": phone,
       
    })

    if serializer.is_valid():
        customer = serializer.save()  # ✅ attach user
        return Response({
            "exists": False,
            "message": "New customer created successfully.",
            "customer": CustomerSerializer(customer).data
        }, status=status.HTTP_201_CREATED)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@permission_classes([IsAuthenticated])
class OrderCreateView(generics.CreateAPIView):
    queryset = Order.objects.all()
    serializer_class = OrderSerializer
     # Require login

    def perform_create(self, serializer):
        # Automatically set 'created_by' field to the logged-in user
        serializer.save(created_by=self.request.user)

# Setup logger


# Constants
DEFAULT_PAGE_SIZE = 15
MAX_PAGE_SIZE = 100
EXPORT_FILENAME_PREFIX = "orders_export"
ALLOWED_EXPORT_FORMATS = ['csv', 'xlsx']
VALID_ORDER_STATUSES = ['pending', 'Completed', 'Delivered_picked']
VALID_PAYMENT_STATUSES = ['pending', 'partial', 'completed']

# Shop constants
SHOP_A = 'Shop A'
SHOP_B = 'Shop B'
HOTEL_USER = 'hotel'
ALL_SHOPS = [SHOP_A, SHOP_B]

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

# ==================== PERMISSION FUNCTIONS ====================

def get_user_profile(user):
    """Safely get user profile"""
    try:
        if hasattr(user, 'userprofile'):
            return user.userprofile
        elif hasattr(user, 'profile'):
            return user.profile
        return None
    except Exception as e:
        logger.error(f"Error getting user profile for {user.id}: {str(e)}")
        return None

def get_user_shops(request):
    """Get the shops associated with the current user based on profile"""
    # ALL authenticated users can access both shops and hotel
    if request.user.is_authenticated:
        return ALL_SHOPS
    
    return []  # Return empty for non-authenticated users

def can_access_all_shops(user):
    """Check if user can access all shops - ALL AUTHENTICATED USERS CAN ACCESS ALL SHOPS"""
    return user.is_authenticated

def can_see_all_orders(user):
    """Check if user can see all orders regardless of creator - ALL AUTHENTICATED USERS CAN SEE ALL ORDERS"""
    return user.is_authenticated

def apply_order_permissions(queryset, request):
    """Apply permission-based filtering to order queryset - NO FILTERING FOR AUTHENTICATED USERS"""
    # All authenticated users can see all orders
    if request.user.is_authenticated:
        return queryset
    
    # Non-authenticated users see nothing
    return queryset.none()

def apply_customer_permissions(queryset, request):
    """Apply permission-based filtering to customer queryset - NO FILTERING FOR AUTHENTICATED USERS"""
    # All authenticated users can see all customers
    if request.user.is_authenticated:
        return queryset
    
    # Non-authenticated users see nothing
    return queryset.none()

def is_admin(user):
    """Check if user has admin privileges"""
    if user.is_superuser:
        return True
    
    user_profile = get_user_profile(user)
    return user_profile and user_profile.user_type == 'admin'

def is_staff(user):
    """Check if user has staff privileges - ALL AUTHENTICATED USERS ARE CONSIDERED STAFF"""
    return user.is_authenticated

def is_hotel_user(user):
    """Check if user is a hotel user"""
    user_profile = get_user_profile(user)
    return user_profile and user_profile.user_type == 'hotel'

# ==================== DECORATORS ====================

def shop_required(view_func):
    """Decorator to ensure user has a shop assignment - ALL AUTHENTICATED USERS HAVE ACCESS"""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.error(request, "Please log in to access this page.")
            return redirect('login')
        return view_func(request, *args, **kwargs)
    return _wrapped_view

def admin_required(view_func):
    """Decorator to ensure user is an admin"""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not is_admin(request.user):
            messages.error(request, "You don't have admin privileges.")
            return redirect('laundry:Laundrydashboard')
        return view_func(request, *args, **kwargs)
    return _wrapped_view

def staff_required(view_func):
    """Decorator to ensure user is staff - ALL AUTHENTICATED USERS ARE STAFF"""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.error(request, "Please log in to access this page.")
            return redirect('login')
        return view_func(request, *args, **kwargs)
    return _wrapped_view

def hotel_user_required(view_func):
    """Decorator to ensure user is a hotel user"""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not is_hotel_user(request.user):
            messages.error(request, "You don't have hotel user privileges.")
            return redirect('laundry:Laundrydashboard')
        return view_func(request, *args, **kwargs)
    return _wrapped_view

# ==================== UTILITY FUNCTIONS ====================
def get_base_order_queryset():
    """Base queryset for orders with common prefetching"""
    return (
        Order.objects.select_related('customer', 'created_by')
        .prefetch_related(
            Prefetch(
                'items',
                queryset=OrderItem.objects.only(
                    'servicetype',
                    'itemname',
                    'quantity',
                    'itemtype',
                    'itemcondition',
                    'total_item_price',
                    'unit_price',
                ),
            )
        )
        .only(
            'id', 'uniquecode', 'order_status', 'payment_status', 'payment_type',
            'shop', 'delivery_date', 'amount_paid', 'balance', 'total_price',
            'created_at', 'customer__name', 'customer__phone','addressdetails', 'created_by'
        )
    )

def check_order_permission(request, order):
    """Check if user has permission to access this order - ALL AUTHENTICATED USERS CAN ACCESS ALL ORDERS"""
    return request.user.is_authenticated

def check_customer_permission(request, customer):
    """Check if user has permission to access this customer - ALL AUTHENTICATED USERS CAN ACCESS ALL CUSTOMERS"""
    return request.user.is_authenticated

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

        # ✅ Get the first name of the user who created the order
        created_by = ""
        if order.created_by and hasattr(order.created_by, 'user'):
            created_by = order.created_by.user.first_name or 'User'
        elif hasattr(order.created_by, 'first_name'):
            created_by = order.created_by.first_name or 'User'


        order_data = {
            'id': order.id,
            'uniquecode': order.uniquecode,
            'customer': {
                'name': order.customer.name,
                'phone': customer_phone,
                
            },
            'created_by': created_by,
            'items': [],
            'amount_paid': float(order.amount_paid or 0),
            'balance': float(order.balance or 0),
            'total_price': float(order.total_price or 0),
            'order_status': order.order_status,
            'payment_status': order.payment_status,
            'payment_type':order.payment_type,
            'shop': order.shop,
            'created_at': order.created_at.strftime('%Y-%m-%d %H:%M') if order.created_at else '',
             # ✅ Display only first name
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

# ==================== VIEWS ====================

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

        # Check if data is empty (no analytics available)
        if not data or all(not v for v in data.values()):
            messages.warning(request, "No data available for the selected period.")
        
        context = analytics.prepare_dashboard_context(request, data, selected_year, selected_month, from_date, to_date)
        context.update({
            'selected_year': selected_year,
            'selected_month': selected_month,
            'from_date': from_date,
            'to_date': to_date,
        })

        return render(request, 'reports.html', context)

    except Exception as e:
        logger.error(f"Error in dashboard view: {str(e)}")
        messages.error(request, "An unexpected error occurred while loading the dashboard.")
        return render(request, 'reports.html', {
            'selected_year': timezone.now().year,
            'selected_month': None,
            'from_date': None,
            'to_date': None,
        })

@login_required
@shop_required
@csrf_protect
def customordertable(request):
    """Order table view with AJAX support and CSRF protection"""
    # Check for export request FIRST - this should work for both AJAX and regular requests
    export_format = request.GET.get('export', '')
    if export_format:
        try:
            # Start with base queryset - include ALL orders (excluding Delivered_picked)
            orders = get_base_order_queryset().exclude(
                order_status__in=['Delivered_picked']
            ).exclude(
                Q(uniquecode__isnull=True) | Q(uniquecode='')
            )

            # Apply permission filtering - ALL authenticated users get all orders
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
                
            # Shop filter - available for all authenticated users
            shop_filter = request.GET.get('shop', '')
            if shop_filter:
                # Validate shop filter against available choices
                valid_shops = [choice[0] for choice in Order.SHOP_CHOICE]
                if shop_filter in valid_shops:
                    filters &= Q(shop=shop_filter)

            if filters:
                orders = orders.filter(filters).distinct()

            # Handle the export
            return handle_export(orders, export_format)
        
        except InvalidDataError as e:
            logger.warning(f"Invalid data in export request: {str(e)}")
            messages.error(request, f"Export failed: {str(e)}")
            return redirect('laundry:customordertable')
        except OrderManagerError as e:
            logger.error(f"Order manager error in export request: {str(e)}")
            messages.error(request, f"Export failed: {str(e)}")
            return redirect('laundry:customordertable')
        except Exception as e:
            logger.error(f"Unexpected error in export request: {str(e)}")
            messages.error(request, "An unexpected error occurred during export.")
            return redirect('laundry:customordertable')
    
    # Check if it's an AJAX request for data loading (but not export)
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return handle_ajax_request(request)
   
    # For initial page load, return basic context
    context = {

        
        'order_status_choices': Order.ORDER_STATUS_CHOICES,
        'payment_status_choices': Order.PAYMENT_STATUS_CHOICES,
        'today': timezone.now().date(),
        'can_see_all_orders': can_see_all_orders(request.user),
        'can_access_all_shops': can_access_all_shops(request.user),
    }
    
    # Add shop choices for all authenticated users to enable filtering
    context['shop_choices'] = Order.SHOP_CHOICE
    
    return render(request, 'Order/orders_table.html', context)

def handle_ajax_request(request):
    """Handle AJAX requests for order data (without export)"""
    try:
        # Start with base queryset - include ALL orders (excluding Delivered_picked)
        orders = get_base_order_queryset().exclude(
            order_status__in=['Delivered_picked']
        ).exclude(
            Q(uniquecode__isnull=True) | Q(uniquecode='')
        )
        #tyty=0721422637
        # Apply permission filtering - ALL authenticated users get all orders
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
            
        # Shop filter - available for all authenticated users
        shop_filter = request.GET.get('shop', '')
        if shop_filter:
            # Validate shop filter against available choices
            valid_shops = [choice[0] for choice in Order.SHOP_CHOICE]
            if shop_filter in valid_shops:
                filters &= Q(shop=shop_filter)

        if filters:
            orders = orders.filter(filters).distinct()

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
            },
            'can_see_all_orders': can_see_all_orders(request.user),
        }
        
        # Add shop choices for all authenticated users in AJAX response
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
@require_POST
@csrf_protect
def update_order_status_ajax(request, order_id, status):
    """Update order status via AJAX with CSRF protection"""
    try:
        validate_order_status(status)
        order = Order.objects.get(id=order_id)

        # Check if user has permission to update this order
        if not check_order_permission(request, order):
            raise PermissionDeniedError("You don't have permission to update this order.")

        # Keep record of previous status
        previous_status = order.order_status

        # ✅ Restrict "Delivered_picked" if payment not complete
        if status == "Delivered_picked" and order.payment_status != "completed":
            return JsonResponse({
                'success': False,
                'message': f"Cannot mark the order Delivered or Picked. Payment is {order.payment_status.upper()}."
            }, status=400)

        # ✅ If allowed, update status
        order.order_status = status

        # ✅ Capture user who updated the order
        if status == "Delivered_picked":
            # Link to the logged-in user’s profile if it exists
            order.updated_by = getattr(request.user, "userprofile", None)

        # Save changes
        order.save()

        logger.info(
            f"Order {order.uniquecode} status changed from {previous_status} to {status} "
            f"by user {request.user.username} (ID: {request.user.id})"
        )

        return JsonResponse({
            'success': True,
            'message': f"Order status updated to {status}."
        })

    except Order.DoesNotExist:
        logger.warning(f"Order not found: {order_id}")
        return JsonResponse({
            'success': False,
            'message': 'Order not found.'
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
            'message': 'An error occurred while updating the order.'
        }, status=500)

@login_required
@shop_required
def order_detail(request, order_id):
    """Get order details for AJAX modal"""
    try:
        order = get_base_order_queryset().get(id=order_id)
        
        # Check if user has permission to view this order - ALL authenticated users can view
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
@require_POST
@csrf_protect
def order_edit(request):
    """Update order via AJAX with transaction safety and CSRF protection"""
    # Check if it's an AJAX request
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'
    
    if not is_ajax:
        return JsonResponse({
            'success': False,
            'message': "Invalid request method or not an AJAX request."
        }, status=400)

    try:
        order_id = request.POST.get('order_id')
        if not order_id:
            raise InvalidDataError("Order ID is required.")

        order = Order.objects.get(id=order_id)
        
        # Check if user has permission to update this order - ALL authenticated users can update
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
        
        # Update payment type
        payment_type = request.POST.get('payment_type')
        if payment_type:
            # Validate payment type
            valid_payment_types = dict(Order.PAYMENT_TYPE_CHOICES)
            if payment_type in valid_payment_types:
                order.payment_type = payment_type
            else:
                raise InvalidDataError(f"Invalid payment type: {payment_type}")
        
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
        
        # Auto-update payment status based on amount paid
        if order.amount_paid == 0:
            order.payment_status = 'pending'
        elif order.balance > 0 and order.balance < order.total_price:
            order.payment_status = 'partial'
        elif order.balance == 0:
            order.payment_status = 'completed'
        
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
@require_POST
@csrf_protect
def order_delete(request, order_code):
    """Delete an order via AJAX with CSRF protection"""
    try:
        # Get the order
        order = Order.objects.only('uniquecode', 'shop').get(uniquecode=order_code)
        
        # Check if user has permission to delete this order - ALL authenticated users can delete
        if not check_order_permission(request, order):
            raise PermissionDeniedError("You don't have permission to delete this order.")
        
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
@require_POST
@csrf_protect
def update_payment_status(request, order_code):
    """Update payment status of an order with CSRF protection"""
    try:
        # Load full order
        order = Order.objects.get(uniquecode=order_code)

        # Check if user has permission - ALL authenticated users have permission
        if not check_order_permission(request, order):
            raise PermissionDeniedError("You don't have permission to update this order.")

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

        #Ensure amount_paid does not exceed total
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
@csrf_protect
def createorder(request):
    """View to handle order creation with Django forms and CSRF protection"""
    context = {}
    return render(request, 'Order/order_form.html')

@login_required
@csrf_protect
def laundrydashboard(request):
    """Laundry dashboard view with CSRF protection - ALL AUTHENTICATED USERS CAN ACCESS"""
    if not request.user.is_authenticated:
        return redirect('login')

    try:
        # Get user's shops - ALL authenticated users get both shops
        user_shops = get_user_shops(request)
        
        # Debug logging
        logger.info(f"User {request.user.email} shops: {user_shops}")
        logger.info(f"Can access all shops: {can_access_all_shops(request.user)}")
        logger.info(f"Can see all orders: {can_see_all_orders(request.user)}")

        # Base queryset - exclude delivered orders from counts
        # ALL authenticated users see all orders
        orders = Order.objects.all()
        # For counts, exclude delivered orders
        count_orders = Order.objects.exclude(order_status='Delivered_picked')
        logger.info(f"Total orders for user: {count_orders.count()}")

        # Calculate overall stats using count_orders (which excludes delivered orders)
        total_orders = count_orders.count()
        pending_orders = count_orders.filter(order_status='pending').count()
        completed_orders = count_orders.filter(order_status='Completed').count()

        # Get recent orders (including delivered)
        recent_orders = orders.select_related('customer').order_by('-created_at')[:10]

        # Shop-specific data for all users
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
        
        # Get specific data for Shop A and Shop B
        shop_a_orders = Order.objects.filter(shop='Shop A').exclude(order_status='Delivered_picked')
        shop_b_orders = Order.objects.filter(shop='Shop B').exclude(order_status='Delivered_picked')
        
        shop_a_data = {
            'total_orders': shop_a_orders.count(),
            'completed_orders': shop_a_orders.filter(order_status='Completed').count(),
            'pending_orders': shop_a_orders.filter(order_status='pending').count(),
            'total_revenue': shop_a_orders.aggregate(total=Sum('total_price'))['total'] or 0
        }
        
        shop_b_data = {
            'total_orders': shop_b_orders.count(),
            'completed_orders': shop_b_orders.filter(order_status='Completed').count(),
            'pending_orders': shop_b_orders.filter(order_status='pending').count(),
            'total_revenue': shop_b_orders.aggregate(total=Sum('total_price'))['total'] or 0
        }

        context = {
            'user_shops': user_shops,
            'total_orders': total_orders,
            'pending_orders': pending_orders,
            'completed_orders': completed_orders,
            'recent_orders': recent_orders,
            'shop_performance': shop_performance,
            'shop_a_data': shop_a_data,
            'shop_b_data': shop_b_data,
            'can_access_all_shops': can_access_all_shops(request.user),
            'can_see_all_orders': can_see_all_orders(request.user),
            'user_type': getattr(request.user, 'user_type', 'unknown'),
        }
        return render(request, 'dashboard.html', context)
        
    except Exception as e:
        logger.error(f"Error in laundry dashboard: {str(e)}", exc_info=True)
        messages.error(request, "An error occurred while loading the dashboard.")
        return render(request, 'dashboard.html', {
            'user_shops': ALL_SHOPS,
            'total_orders': 0,
            'pending_orders': 0,
            'completed_orders': 0,
            'recent_orders': [],
            'shop_performance': {},
            'shop_a_data': None,
            'shop_b_data': None,
            'can_access_all_shops': True,
            'can_see_all_orders': True,
            'user_type': getattr(request.user, 'user_type', 'unknown'),
        })

@login_required
@admin_required
@csrf_protect
def get_laundry_profit_and_hotel(request):
    """
    Display current month data by default without user selection
    Admin only view with CSRF protection
    """
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
                return get_user_shops(request)
        
        # Initialize DashboardAnalytics with the simple admin
        analytics = DashboardAnalytics(SimpleAdmin())
        
        # Get comprehensive dashboard data for the current month
        dashboard_data = analytics.get_dashboard_data(
            request=request,
            selected_year=current_year,
            selected_month=current_month,
            from_date=None,
            to_date=None,
            payment_status=None,
            shop=None
        )
        
        # Extract data from dashboard_data with better validation
        order_stats = dashboard_data.get('order_stats', {})
        expense_stats = dashboard_data.get('expense_stats', {})
        hotel_stats = dashboard_data.get('hotel_stats', {})
        business_growth = dashboard_data.get('business_growth', {})
        
        # Get laundry revenue from dashboard
        laundry_revenue = float(order_stats.get('total_revenue', 0) or 0)
        laundry_expenses = float(expense_stats.get('total_expenses', 0) or 0)
        laundry_profit = laundry_revenue - laundry_expenses
        
        # Calculate hotel metrics
        hotel_revenue = float(hotel_stats.get('total_revenue', 0) or 0)
        hotel_expenses = float(hotel_stats.get('total_expenses', 0) or 0)
        hotel_profit = float(hotel_stats.get('net_profit', 0) or 0)
        
        # Calculate totals
        total_revenue_from_growth = float(business_growth.get('total_revenue', 0) or 0)
        total_profit_from_growth = float(business_growth.get('net_profit', 0) or 0)
        
        # Use business_growth values if they seem correct, otherwise calculate manually
        if total_revenue_from_growth > 0:
            total_revenue = total_revenue_from_growth
            total_profit = total_profit_from_growth
        else:
            total_revenue = laundry_revenue + hotel_revenue
            total_profit = laundry_profit + hotel_profit
        
        # **CRITICAL FIX**: Verify revenue with multiple date field queries
        try:
            from django.db.models import Sum
            
            # Query 1: Using delivery_date (same as dashboard)
            delivery_date_revenue = OrderItem.objects.filter(
                order__delivery_date__year=current_year,
                order__delivery_date__month=current_month,
                order__order_status__in=['pending', 'Completed', 'Delivered_picked']
            ).aggregate(total=Sum('total_item_price'))['total'] or 0
            
            # Query 2: Using created_at (might be what reports use)
            created_date_revenue = OrderItem.objects.filter(
                order__created_at__year=current_year,
                order__created_at__month=current_month,
                order__order_status__in=['pending', 'Completed', 'Delivered_picked']
            ).aggregate(total=Sum('total_item_price'))['total'] or 0
            
            print(f"Dashboard Laundry Revenue: {laundry_revenue}")
            print(f"Delivery Date Revenue: {delivery_date_revenue}")
            print(f"Created Date Revenue: {created_date_revenue}")
            
            # If there's a significant discrepancy, use the most reliable source
            delivery_diff = abs(float(delivery_date_revenue) - laundry_revenue)
            created_diff = abs(float(created_date_revenue) - laundry_revenue)
            
            # Use the most consistent value
            if delivery_diff <= created_diff and delivery_diff <= 1:
                # Dashboard and delivery date are consistent
                final_laundry_revenue = laundry_revenue
            elif created_diff <= delivery_diff and created_diff <= 1:
                # Created date is consistent with something
                final_laundry_revenue = float(created_date_revenue)
            else:
                # Significant discrepancies - use delivery date (dashboard standard)
                final_laundry_revenue = float(delivery_date_revenue)
                print(f"Revenue discrepancies detected. Using delivery date standard: {final_laundry_revenue}")
            
            # Update the revenue if different from dashboard
            if final_laundry_revenue != laundry_revenue:
                print(f"Correcting laundry revenue from {laundry_revenue} to {final_laundry_revenue}")
                laundry_revenue = final_laundry_revenue
                # Recalculate all dependent values
                laundry_profit = laundry_revenue - laundry_expenses
                total_revenue = laundry_revenue + hotel_revenue
                total_profit = laundry_profit + hotel_profit
                
        except Exception as db_error:
            print(f"Database verification query failed: {db_error}")
        
        # Prepare context with formatted values
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
        
        print(f"Final Dashboard Data - Laundry: KSh {laundry_revenue:,.2f}, Hotel: KSh {hotel_revenue:,.2f}, Total: KSh {total_revenue:,.2f}")
        
        return render(request, 'Generaldashboard.html', context)
        
    except Exception as e:
        print(f"Error in get_laundry_profit_and_hotel: {str(e)}", exc_info=True)
        
        # Convert month number to month name for error case too
        month_names = {
            1: 'January', 2: 'February', 3: 'March', 4: 'April',
            5: 'May', 6: 'June', 7: 'July', 8: 'August',
            9: 'September', 10: 'October', 11: 'November', 12: 'December'
        }
        current_month_name = month_names.get(current_date.month, 'Unknown')
        
        return render(request, 'Generaldashboard.html', {
            'total_revenue': 0.0, 'laundry_revenue': 0.0, 'laundry_expenses': 0.0,
            'laundry_profit': 0.0, 'hotel_revenue': 0.0, 'hotel_expenses': 0.0,
            'hotel_profit': 0.0, 'total_profit': 0.0, 
            'current_year': current_date.year,
            'current_month': current_date.month,
            'current_month_name': current_month_name,
            'dashboard_title': f"{current_month_name} {current_date.year} Dashboard",
            'error_message': f"Error loading dashboard data: {str(e)}"
        })

@login_required
@csrf_protect
def logout_view(request):
    """Log out the current user and redirect to login page with CSRF protection"""
    try:
        auth_logout(request)
        messages.info(request, "You have been successfully logged out.")
    except Exception as e:
        logger.error(f"Error during logout: {str(e)}")
        messages.error(request, "An error occurred during logout.")
    
    return redirect('login')

# ==================== DEBUG VIEW ====================
# In your views.py


def get_current_month_financials(request):
    """View function to return current month financial data as JSON"""
    today = timezone.now().date()
    
    current_month_orders = Order.objects.filter(
        created_at__year=today.year,
        created_at__month=today.month
    )
    
    revenue = current_month_orders.aggregate(
        total=Sum('amount_paid')
    )['total'] or Decimal('0.00')
    
    balance = current_month_orders.aggregate(
        total=Sum('balance')
    )['total'] or Decimal('0.00')
    
    data = {
        'revenue': float(revenue),
        'balance': float(balance),
        'order_count': current_month_orders.count(),
        'month': today.strftime('%B %Y')
    }
    
    return JsonResponse(data)
