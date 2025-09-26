from decimal import Decimal, InvalidOperation
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django_daraja.mpesa.core import MpesaClient
import json
import logging
import datetime
from functools import wraps
from datetime import datetime, date, timedelta

# Django imports
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.db.models import Q, Prefetch, Sum, Count, Avg,F,ExpressionWrapper, DecimalField, Value
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.contrib.auth.forms import AuthenticationForm

from django.db import IntegrityError
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth import get_user_model
from django.db.models.functions import Coalesce
from django.utils.timezone import now

from django.db import transaction

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
        else:
            # If no shop is assigned, return empty list
            return []
    except Exception:
        # If any error occurs, return empty list
        return []

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

@login_required
def debug_user_info(request):
    """Debug view to check user shop assignments"""
    user_shops = get_user_shops(request)
    laundry_profile = getattr(request.user, 'laundry_profile', None)
    
    debug_info = {
        'username': request.user.username,
        'is_superuser': request.user.is_superuser,
        'is_staff': request.user.is_staff,
        'user_shops': user_shops,
        'laundry_profile_exists': laundry_profile is not None,
        'laundry_profile_shop': laundry_profile.shop if laundry_profile else None,
        'user_type': getattr(request.user, 'user_type', None),
        'app_type': getattr(request.user, 'app_type', None),
    }
    
    return JsonResponse(debug_info)

@login_required
def debug_shop_values(request):
    """Debug view to check all shop values in the database"""
    # Get unique shop values from orders
    order_shops = Order.objects.values_list('shop', flat=True).distinct()
    order_shops = [shop for shop in order_shops if shop]  # Remove None values
    
    # Get unique shop values from laundry profiles
    laundry_shops = LaundryProfile.objects.values_list('shop', flat=True).distinct()
    laundry_shops = [shop for shop in laundry_shops if shop]  # Remove None values
    
    debug_info = {
        'order_shops': list(order_shops),
        'laundry_shops': list(laundry_shops),
        'current_user_shops': get_user_shops(request),
    }
    
    return JsonResponse(debug_info)

def is_admin(user):
    return (user.is_superuser or 
            getattr(user, 'user_type', None) == 'admin')

def is_staff(user):
    return (user.is_staff or 
            getattr(user, 'user_type', None) in ['admin', 'staff'])

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
            'itemcondition', 'total_item_price',
        ))
    ).only(
        'uniquecode', 'order_status', 'payment_status','payment_type',
        'shop', 'delivery_date', 'amount_paid', 'balance', 'total_price', 'created_at', 
        'customer__name', 'customer__phone', 'customer__address', 'addressdetails'
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

# Views
@login_required
@admin_required
def dashboard_view(request):
    current_year = timezone.now().year
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
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')

    try:
        if from_date:
            from_date = datetime.strptime(from_date, "%Y-%m-%d").date()
        if to_date:
            to_date = datetime.strptime(to_date, "%Y-%m-%d").date()
    except ValueError:
        from_date = None
        to_date = None

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

@login_required
@shop_required
def customordertable(request):
    # Start with base queryset - include ALL orders (excluding Delivered_picked)
    orders = get_base_order_queryset().exclude(
        order_status__in=['Delivered_picked']
    ).exclude(
        Q(uniquecode__isnull=True) | Q(uniquecode='')
    )

    # Apply permission filtering
    orders = apply_order_permissions(orders, request)

    # Apply shop filter for admin users
    if request.user.is_superuser:
        shop_filter = request.GET.get('shop', '')
        if shop_filter:
            orders = orders.filter(shop=shop_filter)

    # Apply filters in a single optimized block
    filters = Q()
    
    status_filter = request.GET.get('order_status', '')
    if status_filter:
        filters &= Q(order_status=status_filter)
        
    payment_filter = request.GET.get('payment_status', '')
    if payment_filter:
        filters &= Q(payment_status=payment_filter)

    search_query = request.GET.get('search', '')
    if search_query:
        filters &= (
            Q(uniquecode__icontains=search_query) |
            Q(customer__name__icontains=search_query) |
            Q(customer__phone__icontains=search_query) |
            Q(items__servicetype__icontains=search_query) |
            Q(items__itemname__icontains=search_query)
        )

    if filters:
        orders = orders.filter(filters).distinct()

    # Handle export before pagination
    export_format = request.GET.get('export', '')
    if export_format:
        return handle_export(orders, export_format)

    # Order by creation date and paginate
    orders = orders.order_by('-created_at')

    # Get counts for stats cards before pagination
    stats = get_order_stats(orders)

    # Pagination
    paginator = Paginator(orders, 15)
    page_number = request.GET.get('page')
    page_obj = get_page_obj(paginator, page_number)

    context = {
        'orders': page_obj,
        **stats,
        'order_status_choices': Order.ORDER_STATUS_CHOICES,
        'payment_status_choices': Order.PAYMENT_STATUS_CHOICES,
        'today': timezone.now().date(),
        'current_status_filter': status_filter,
        'current_payment_filter': payment_filter,
        'search_query': search_query,
        'shop_filter': request.GET.get('shop', '') if request.user.is_superuser else '',
    }
    return render(request, 'Admin/orders_table.html', context)


# Helper functions for better organization
def handle_export(orders, export_format):
    """Handle export functionality"""
    dataset = OrderResource().export(queryset=orders)
    timestamp = timezone.now().strftime('%Y-%m-%d_%H-%M-%S')
    
    if export_format == 'csv':
        response = HttpResponse(dataset.csv, content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="orders_export_{timestamp}.csv"'
        return response
        
    elif export_format == 'xlsx':
        xlsx_data = dataset.export('xlsx')
        response = HttpResponse(
            xlsx_data, 
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename="orders_export_{timestamp}.xlsx"'
        return response


def get_order_stats(orders):
    """Get order statistics in optimized way"""
    status_counts = orders.aggregate(
        total=Count('id'),
        pending=Count('id', filter=Q(order_status='pending')),
        completed=Count('id', filter=Q(order_status='Completed')),
        delivered=Count('id', filter=Q(order_status='delivered')),
        in_progress=Count('id', filter=Q(order_status='in_progress'))
    )
    
    return {
        'total_orders': status_counts['total'],
        'pending_orders': status_counts['pending'],
        'completed_orders': status_counts['completed'],
        'delivered_orders': status_counts['delivered'],
        'in_progress_orders': status_counts['in_progress'],
    }


def get_page_obj(paginator, page_number):
    """Handle pagination safely"""
    try:
        return paginator.page(page_number)
    except PageNotAnInteger:
        return paginator.page(1)
    except EmptyPage:
        return paginator.page(paginator.num_pages)
@login_required
@shop_required
def order_detail(request, order_code):
    """View detailed information about a specific order"""
    try:
        order = get_base_order_queryset().get(uniquecode=order_code)
        
        # Check if user has permission to view this order
        if not check_order_permission(request, order):
            raise Http404("You don't have permission to view this order.")
            
        context = {
            'order': order,
            'today': timezone.now().date(),
        }
        return render(request, 'Admin/order_detail.html', context)
        
    except Order.DoesNotExist:
        raise Http404("Order not found")

@login_required
@shop_required
def order_edit(request, order_code):
    """Edit an existing order with proper payment status and balance recalculation"""
    try:
        order = get_base_order_queryset().get(uniquecode=order_code)
        
        # Check if user has permission to edit this order
        if not check_order_permission(request, order):
            messages.error(request, "You don't have permission to edit this order.")
            return redirect('laundry:customordertable')
        
        # Get user shops here so it's available for both GET and POST requests
        user_shops = get_user_shops(request)
        
        if request.method == 'POST':
            # Create a mutable copy of the POST data
            post_data = request.POST.copy()
            
            # For users with only one shop, override the shop value
            if user_shops and len(user_shops) == 1:
                post_data['shop'] = user_shops[0]
            
            # Update customer information
            customer = order.customer
            customer_form = CustomerForm(post_data, instance=customer)
            
            # Update order information
            order_form = OrderForm(post_data, instance=order)
            
            # Handle order items
            OrderItemFormSet = forms.formset_factory(OrderItemForm, extra=0)
            item_formset = OrderItemFormSet(post_data, prefix='items')
            
            if customer_form.is_valid() and order_form.is_valid() and item_formset.is_valid():
                try:
                    with transaction.atomic():
                        # Save customer
                        customer_form.save()
                        
                        # Save order first without recalculating totals
                        updated_order = order_form.save(commit=False)
                        
                        # Handle order items - delete existing and create new ones
                        order.items.all().delete()
                        total_price = Decimal('0.00')
                        
                        for form in item_formset:
                            if form.cleaned_data and not form.cleaned_data.get('DELETE', False):
                                order_item = form.save(commit=False)
                                order_item.order = updated_order
                                order_item.save()
                                # Calculate total item price and add to order total
                                order_item.total_item_price = (order_item.unit_price or Decimal('0.00'))
                                order_item.save()
                                total_price += order_item.total_item_price
                        
                        # Update order totals and payment status
                        updated_order.total_price = total_price
                        updated_order.balance = total_price - updated_order.amount_paid
                        
                        # Payment status will be automatically set in the save() method
                        # based on amount_paid and balance
                        updated_order.save()
                    
                    messages.success(request, f'Order {order.uniquecode} updated successfully!')
                    return redirect('laundry:customordertable')
                    
                except Exception as e:
                    messages.error(request, f'Error updating order: {str(e)}')
                    logger.error(f"Order update error: {str(e)}")
            else:
                # Collect all form errors
                error_messages = []
                if not customer_form.is_valid():
                    for field, errors in customer_form.errors.items():
                        for error in errors:
                            error_messages.append(f"Customer {field}: {error}")
                
                if not order_form.is_valid():
                    for field, errors in order_form.errors.items():
                        for error in errors:
                            error_messages.append(f"Order {field}: {error}")
                
                if not item_formset.is_valid():
                    for i, form in enumerate(item_formset):
                        if not form.is_valid():
                            for field, errors in form.errors.items():
                                for error in errors:
                                    error_messages.append(f"Item {i+1} {field}: {error}")
                
                messages.error(request, 'Please correct the following errors: ' + '; '.join(error_messages))
        else:
            # GET request - populate forms with existing data
            customer_form = CustomerForm(instance=order.customer)
            order_form = OrderForm(instance=order)
            
            # Prepare initial data for order items
            initial_items = []
            for item in order.items.all():
                initial_items.append({
                    'servicetype': item.servicetype,
                    'itemtype': item.itemtype,
                    'itemname': item.itemname,
                    'quantity': item.quantity,
                    'itemcondition': item.itemcondition,
                    'unit_price': item.unit_price,
                    'additional_info': item.additional_info,
                })
            
            OrderItemFormSet = forms.formset_factory(OrderItemForm, extra=1)
            item_formset = OrderItemFormSet(prefix='items', initial=initial_items)
        
        context = {
            'customer_form': customer_form,
            'order_form': order_form,
            'item_formset': item_formset,
            'order': order,
            'user_has_single_shop': user_shops and len(user_shops) == 1,
            'user_shop': user_shops[0] if user_shops else '',
            'editing': True,
        }
        
        return render(request, 'Admin/order_edit_form.html', context)
        
    except Order.DoesNotExist:
        raise Http404("Order not found")
@login_required
@shop_required
def order_delete(request, order_code):
    """Delete an order"""
    try:
        # Only include fields that exist in your Order model
        order = Order.objects.only('uniquecode', 'shop').get(uniquecode=order_code)
        
        # Check if user has permission to delete this order
        if not check_order_permission(request, order):
            messages.error(request, "You don't have permission to delete this order.")
            return redirect('laundry:customordertable')
        
        if request.method == 'POST':
            order_code = order.uniquecode
            order.delete()
            messages.success(request, f'Order {order_code} deleted successfully!')
            return redirect('laundry:customordertable')
        
        context = {
            'order': order,
        }
        return render(request, 'Admin/order_confirm_delete.html', context)
        
    except Order.DoesNotExist:
        raise Http404("Order not found")
@login_required
@shop_required
@require_POST
def update_order_status(request, order_code, status):
    order = get_object_or_404(Order, uniquecode=order_code)

    # Permission check
    if not check_order_permission(request, order):
        message = "You don't have permission to update this order."
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"success": False, "message": message}, status=403)
        messages.error(request, message)
        return redirect('laundry:customordertable')

    # Validate status
    valid_statuses = dict(Order.ORDER_STATUS_CHOICES).keys()
    if status not in valid_statuses:
        message = f"Invalid status: {status}"
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"success": False, "message": message}, status=400)
        messages.error(request, message)
        return redirect('laundry:customordertable')

    # Update order
    order.order_status = status
    order.save()

    message = f"Order {order_code} has been marked as {order.get_order_status_display()}."

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({
            "success": True,
            "message": message,
            "new_status": status,
            "status_display": order.get_order_status_display()
        })

    # fallback for normal POST (non-AJAX)
    messages.success(request, message)
    return redirect(request.META.get('HTTP_REFERER', 'laundry:customordertable'))

@login_required
@shop_required
def update_payment_status(request, order_code):
    """Update payment status of an order"""
    try:
        # Load full order (not limiting fields to ensure updates work)
        order = Order.objects.get(uniquecode=order_code)

        # Check if user has permission
        if not check_order_permission(request, order):
            return JsonResponse({
                'success': False,
                'message': "You don't have permission to update this order."
            }, status=403)

        if request.method == 'POST':
            payment_status = request.POST.get('payment_status')
            amount_paid_raw = request.POST.get('amount_paid', "0")

            if payment_status in dict(Order.PAYMENT_STATUS_CHOICES):
                order.payment_status = payment_status

                # Safely convert amount_paid
                try:
                    amount_paid = Decimal(amount_paid_raw)
                except (InvalidOperation, TypeError, ValueError):
                    return JsonResponse({
                        'success': False,
                        'message': 'Invalid amount entered.'
                    }, status=400)

                # Ensure amount_paid is not negative
                if amount_paid < 0:
                    return JsonResponse({
                        'success': False,
                        'message': 'Amount paid cannot be negative.'
                    }, status=400)

                # Ensure amount_paid does not exceed total
                if amount_paid > order.total_price:
                    amount_paid = order.total_price

                order.amount_paid = amount_paid
                order.save()

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
            else:
                return JsonResponse({
                    'success': False,
                    'message': 'Invalid payment status.'
                }, status=400)

        return JsonResponse({
            'success': False,
            'message': 'Invalid request method.'
        }, status=405)

    except Order.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'Order not found.'
        }, status=404)

@login_required
@shop_required
def createorder(request):
    """View to handle order creation with Django forms"""
    user_shops = get_user_shops(request)
    default_shop = user_shops[0] if user_shops else None

    if request.method == 'POST':
        post_data = request.POST.copy()

        # Force shop if user has only one
        if user_shops and len(user_shops) == 1:
            # Use the shop name directly instead of trying to get id from string
            post_data['shop'] = user_shops[0]

        # Default order_status
        if not post_data.get('order_status'):
            post_data['order_status'] = 'pending'

        # --- Customer handling ---
        phone = post_data.get('phone', '').strip()
        customer_id = post_data.get('customer_id', '').strip()
        customer = None
        customer_exists = False

        # Check if we have a customer ID (from selection)
        if customer_id:
            try:
                customer = Customer.objects.get(id=customer_id)
                customer_exists = True
                # Update customer details if changed
                if customer.name != post_data.get('name', ''):
                    customer.name = post_data.get('name', '')
                    customer.save()
            except Customer.DoesNotExist:
                customer_exists = False
        elif phone:
            # Fallback to phone lookup
            try:
                customer = Customer.objects.get(phone=phone)
                customer_exists = True
                # Update name if different
                if customer.name != post_data.get('name', ''):
                    customer.name = post_data.get('name', '')
                    customer.save()
            except Customer.DoesNotExist:
                customer_exists = False

        if customer_exists:
            customer_form_is_valid = True
            customer_form = None
        else:
            # Validate new customer form
            customer_form = CustomerForm(post_data)
            customer_form_is_valid = customer_form.is_valid()

        # --- Order + Items ---
        order_form = OrderForm(post_data)
        OrderItemFormSet = forms.formset_factory(OrderItemForm, extra=0)
        item_formset = OrderItemFormSet(post_data, prefix='items')

        order_form_is_valid = order_form.is_valid()
        item_formset_is_valid = item_formset.is_valid()

        if all([customer_form_is_valid, order_form_is_valid, item_formset_is_valid]):
            try:
                # Save or reuse customer
                if not customer_exists:
                    customer = customer_form.save()

                # Save order - don't commit yet to let the model generate the unique code
                order = order_form.save(commit=False)
                order.customer = customer
                order.created_by = request.user
                
                if not order.order_status:
                    order.order_status = 'pending'
                
                # Let the model's save() method generate the unique code
                # Don't set total_price yet as items haven't been saved
                order.total_price = 0  # Temporary value
                
                order.balance = -order.amount_paid  # Temporary value
                
                # Save the order to generate the unique code
                order.save()

                # Save items
                for form in item_formset:
                    if form.cleaned_data and not form.cleaned_data.get('DELETE', False):
                        order_item = form.save(commit=False)
                        order_item.order = order
                        # Calculate item total if needed
                        if hasattr(order_item, 'quantity') and hasattr(order_item, 'unit_price'):
                            if hasattr(order_item, 'total_item_price'):
                                order_item.total_item_price = order_item.quantity * order_item.unit_price
                        order_item.save()

                # Now update the totals after all items are saved
                total_price = sum(
                   item.unit_price 
                    for item in order.items.all()
                )
                order.total_price = total_price
                order.balance = total_price - (order.amount_paid or 0)
                
                # Save again to update totals
                order.save()

                messages.success(request, f'Order created successfully! Code: {order.uniquecode}')
                return redirect('laundry:customordertable')

            except IntegrityError as e:
                if 'uniquecode' in str(e):
                    # This shouldn't happen with your model's save method, but just in case
                    logger.error(f"Order creation error (unique code conflict): {str(e)}")
                    messages.error(request, 'Could not create order due to system error. Please try again.')
                else:
                    logger.error(f"Order creation error: {str(e)}")
                    messages.error(request, f'Error creating order: {str(e)}')
            except Exception as e:
                logger.error(f"Order creation error: {str(e)}")
                messages.error(request, f'Error creating order: {str(e)}')

        else:
            # Collect errors
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

    else:  # GET
        customer_form = CustomerForm()
        order_form = OrderForm()
        if user_shops and len(user_shops) == 1:
            # Set the initial value to the shop name, not the id
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
    if not request.user.is_authenticated:
        return redirect('login')

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

    # Calculate stats using count_orders (which excludes delivered orders)
    total_orders = count_orders.count()
    pending_orders = count_orders.filter(order_status='pending').count()
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
                shop_orders = Order.objects.filter(shop=shop).exclude(order_status='Delivered_picked')
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
    }
    return render(request, 'Admin/dashboard.html', context)

# OR: from datetime import datetime
def get_laundry_profit_and_hotel(request, selected_year=None):
    """
    Highly optimized version with minimal database queries
    """
    if not request.user.is_authenticated or not request.user.is_superuser:
        return redirect('login')

    try:
        current_date = now()
        current_year = current_date.year
        current_month = current_date.month
        
        # Calculate date range once
        start_date = datetime(current_year, current_month, 1).date()
        end_date = datetime(current_year + 1, 1, 1).date() if current_month == 12 else \
                  datetime(current_year, current_month + 1, 1).date()
        
        # HOTEL CALCULATIONS - 2 queries total
        from HotelApp.models import HotelOrderItem, HotelExpenseRecord
        
        # Use database-level calculation for hotel revenue
        hotel_data = HotelOrderItem.objects.select_related('food_item', 'order').filter(
            order__created_at__date__range=[start_date, end_date]
        ).aggregate(
            revenue=Sum(F('quantity') * F('food_item__price'), 
                       output_field=DecimalField(max_digits=12, decimal_places=2))
        )
        
        hotel_expenses_data = HotelExpenseRecord.objects.filter(
            date__range=[start_date, end_date]
        ).aggregate(expenses=Sum('amount'))
        
        hotel_revenue = hotel_data['revenue'] or Decimal('0')
        hotel_expenses = hotel_expenses_data['expenses'] or Decimal('0')
        hotel_profit = hotel_revenue - hotel_expenses
        
        # LAUNDRY CALCULATIONS - 2 queries total
        laundry_revenue_data = Order.objects.filter(
            created_at__date__range=[start_date, end_date]
        ).aggregate(revenue=Sum('total_price'))
        
        laundry_expenses_data = ExpenseRecord.objects.filter(
            date__range=[start_date, end_date]
        ).aggregate(expenses=Sum('amount'))
        
        laundry_revenue = laundry_revenue_data['revenue'] or Decimal('0')
        laundry_expenses = laundry_expenses_data['expenses'] or Decimal('0')
        laundry_profit = laundry_revenue - laundry_expenses
        
        # Prepare context
        context = {
            'total_revenue': float(hotel_revenue + laundry_revenue),
            'laundry_revenue': float(laundry_revenue),
            'laundry_expenses': float(laundry_expenses),
            'laundry_profit': float(laundry_profit),
            'hotel_revenue': float(hotel_revenue),
            'hotel_expenses': float(hotel_expenses),
            'hotel_profit': float(hotel_profit),
            'total_profit': float(hotel_profit + laundry_profit),
            'current_month': current_date.strftime('%B %Y'),
        }
        
        return render(request, 'Admin/Generaldashboard.html', context)
        
    except Exception as e:
        logger.error(f"Error in get_laundry_profit_and_hotel: {e}")
        return render(request, 'Admin/Generaldashboard.html', {
            'total_revenue': 0.0, 'laundry_revenue': 0.0, 'laundry_expenses': 0.0,
            'laundry_profit': 0.0, 'hotel_revenue': 0.0, 'hotel_expenses': 0.0,
            'hotel_profit': 0.0, 'total_profit': 0.0, 'current_month': now().strftime('%B %Y')
        })
def Reportsdashboard(request):
    # Initialize DashboardAnalytics with a mock admin instance
    class MockAdmin:
        def get_user_shops(self, request):
            return get_user_shops(request)
    
    mock_admin = MockAdmin()
    analytics = DashboardAnalytics(mock_admin)
    
    # Get current year and month
    current_year = timezone.now().year
    current_month = timezone.now().month
    
    # Get dashboard data
    data = analytics.get_dashboard_data(request, current_year, current_month)
    
    # Prepare context
    context = analytics.prepare_dashboard_context(request, data, current_year, current_month)
    
    return render(request, 'dashboard.html', context)

def initiatepayment(request, order_id):
    if request.method == 'POST':
        order = get_object_or_404(Order, id=order_id)
        
        # Check if order is already fully paid
        if order.balance <= 0:
            return JsonResponse({
                'success': False, 
                'message': f"Order {order.uniquecode} is already fully paid."
            })
            
        # Get the amount from the POST data
        try:
            amount = int(request.POST.get('amount', order.balance))
        except (ValueError, TypeError):
            amount = int(order.balance)
            
        # Validate amount
        if amount <= 0:
            return JsonResponse({
                'success': False,
                'message': 'Invalid payment amount'
            })
            
        if amount > order.balance:
            return JsonResponse({
                'success': False,
                'message': f'Amount cannot exceed balance of KSh {order.balance}'
            })
            
        cl = MpesaClient()
        phone_number = str(order.customer.phone)
        
        # Format phone number correctly (remove leading 0 if present and add country code)
        if phone_number.startswith('0'):
            phone_number = '254' + phone_number[1:]
        elif phone_number.startswith('+254'):
            phone_number = phone_number[1:]
        elif phone_number.startswith('254'):
            phone_number = phone_number
        else:
            phone_number = '254' + phone_number
            
        account_reference = f"ORDER{order.id}"
        transaction_desc = f"Payment for order {order.uniquecode}"
        
        # For development/testing, you can use a mock callback URL
        # For production, you need a real publicly accessible HTTPS URL
        if settings.DEBUG:
            # Use a service like ngrok or webhook.site for development
            callback_url = "https://webhook.site/your-unique-url"  # Replace with your webhook URL
            # OR use ngrok: callback_url = "https://your-ngrok-url.ngrok.io/daraja/stk_push/"
        else:
            # Production callback URL
            callback_url = "https://yourdomain.com/daraja/stk_push/"
        
        logger.info(f"Attempting payment initiation: Phone: {phone_number}, Amount: {amount}, Callback: {callback_url}")
        
        try:
            response = cl.stk_push(phone_number, amount, account_reference, transaction_desc, callback_url)
            response_data = response.json()
            
            logger.info(f"M-Pesa API Response: {response_data}")
            
            if 'ResponseCode' in response_data and response_data['ResponseCode'] == '0':
                checkout_request_id = response_data.get('CheckoutRequestID')
                if checkout_request_id:
                    order.checkout_request_id = checkout_request_id
                    order.payment_status = 'processing'
                    order.save()
                    
                    logger.info(f"Payment initiated successfully for order {order.uniquecode}. CheckoutRequestID: {checkout_request_id}")
                    
                    return JsonResponse({
                        'success': True,
                        'message': f"Payment initiated for order {order.uniquecode}. Check your phone to complete payment.",
                        'checkout_request_id': checkout_request_id
                    })
                else:
                    error_message = "No CheckoutRequestID received from M-Pesa"
                    logger.error(f"Payment initiation failed: {error_message}")
                    return JsonResponse({
                        'success': False,
                        'message': f"Payment initiation failed: {error_message}"
                    })
            else:
                error_message = response_data.get('errorMessage', 'Unknown error occurred')
                customer_message = response_data.get('CustomerMessage', '')
                logger.error(f"M-Pesa API error: {error_message}, CustomerMessage: {customer_message}")
                return JsonResponse({
                    'success': False,
                    'message': f"Payment initiation failed: {customer_message or error_message}"
                })
                
        except Exception as e:
            logger.error(f"Error initiating payment for order {order.uniquecode}: {str(e)}")
            return JsonResponse({
                'success': False,
                'message': f"Error initiating payment: {str(e)}"
            })
    
    return JsonResponse({'success': False, 'message': 'Invalid request method'})

@csrf_exempt
def stk_push_callback(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            logger.info(f"STK Push callback received: {data}")

            stk_callback = data.get("Body", {}).get("stkCallback", {})
            result_code = stk_callback.get("ResultCode")
            checkout_request_id = stk_callback.get("CheckoutRequestID")
            result_desc = stk_callback.get("ResultDesc", "")
            callback_metadata = stk_callback.get("CallbackMetadata", {}).get("Item", [])

            if result_code == 0:
                # Payment was successful
                try:
                    order = Order.objects.get(checkout_request_id=checkout_request_id)
                    
                    # Extract payment details from metadata
                    balance_paid = 0
                    mpesa_receipt_number = ""
                    
                    for item in callback_metadata:
                        if item.get("Name") == "Amount":
                            balance_paid = item.get("Value", 0)
                        elif item.get("Name") == "MpesaReceiptNumber":
                            mpesa_receipt_number = item.get("Value", "")
                    
                    # Update order with payment details - set balance to zero
                    order.balance = 0
                    order.total_price =  order.amount_paid+balance_paid  # Assuming full payment
                    order.payment_date = timezone.now()
                    order.save()
                    
                    logger.info(f"✅ Order {order.id} marked as paid. Receipt: {mpesa_receipt_number}, Amount: {balance_paid}")
                    
                except Order.DoesNotExist:
                    logger.error(f"❌ No order found for CheckoutRequestID {checkout_request_id}")
                    return JsonResponse({'ResultCode': 1, 'ResultDesc': 'Order not found'})
                    
            else:
                # Payment failed
                try:
                    order = Order.objects.get(checkout_request_id=checkout_request_id)
                    order.payment_status = 'failed'
                    order.save()
                    logger.error(f"❌ Payment failed for order {order.id}: {result_desc}")
                except Order.DoesNotExist:
                    logger.error(f"❌ Payment failed for unknown order with CheckoutRequestID {checkout_request_id}: {result_desc}")
        
            return JsonResponse({'ResultCode': 0, 'ResultDesc': 'Success'})
            
        except json.JSONDecodeError:
            logger.error("Invalid JSON in callback")
            return JsonResponse({'ResultCode': 1, 'ResultDesc': 'Invalid JSON'})
        except Exception as e:
            logger.error(f"Unexpected error in callback: {e}")
            return JsonResponse({'ResultCode': 1, 'ResultDesc': 'Server error'})
            
    return JsonResponse({'ResultCode': 1, 'ResultDesc': 'Invalid request method'})

def logout_view(request):
    """Log out the current user and redirect to login page"""
    auth_logout(request)
    messages.info(request, "You have been successfully logged out.")
    return redirect('login')









from django.http import JsonResponse
from django.db.models import Sum
from django.views import View
from .models import Order, ExpenseRecord, OrderItem
import json

class DebugFinancialDataView(View):
    def get(self, request):
        """
        Debug view to sum up all expenses and order totals in the database
        """
        try:
            # Sum up all orders' total_price
            orders_summary = Order.objects.aggregate(
                total_orders_revenue=Sum('total_price'),
                total_orders_count=Sum('id', distinct=True),  # Count distinct orders
                total_amount_paid=Sum('amount_paid'),
                total_balance=Sum('balance')
            )
            
            # Sum up all expenses
            expenses_summary = ExpenseRecord.objects.aggregate(
                total_expenses=Sum('amount'),
                expenses_count=Sum('id', distinct=True)  # Count distinct expenses
            )
            
            # Get expenses by shop
            expenses_by_shop = list(ExpenseRecord.objects.values('shop').annotate(
                shop_expenses=Sum('amount'),
                expense_count=Sum('id', distinct=True)
            ).order_by('-shop_expenses'))
            
            # Get revenue by shop
            revenue_by_shop = list(Order.objects.values('shop').annotate(
                shop_revenue=Sum('total_price'),
                orders_count=Sum('id', distinct=True),
                amount_paid=Sum('amount_paid'),
                balance=Sum('balance')
            ).order_by('-shop_revenue'))
            
            # Get order items summary
            order_items_summary = OrderItem.objects.aggregate(
                total_items_value=Sum('total_item_price'),
                total_items_count=Sum('quantity'),
                distinct_items=Sum('id', distinct=True)
            )
            
            # Calculate net profit/loss
            total_revenue = orders_summary['total_orders_revenue'] or 0
            total_expenses = expenses_summary['total_expenses'] or 0
            net_profit = total_revenue - total_expenses
            
            # Get some sample data for verification
            sample_orders = list(Order.objects.values('uniquecode', 'total_price', 'amount_paid', 'balance')[:5])
            sample_expenses = list(ExpenseRecord.objects.values('field__label', 'shop', 'amount', 'date')[:5])
            
            response_data = {
                'status': 'success',
                'summary': {
                    'financial_overview': {
                        'total_revenue': float(total_revenue),
                        'total_expenses': float(total_expenses),
                        'net_profit_loss': float(net_profit),
                        'total_amount_collected': float(orders_summary['total_amount_paid'] or 0),
                        'total_balance_outstanding': float(orders_summary['total_balance'] or 0)
                    },
                    'orders_breakdown': {
                        'total_orders': orders_summary['total_orders_count'] or 0,
                        'total_orders_revenue': float(orders_summary['total_orders_revenue'] or 0),
                        'total_amount_paid': float(orders_summary['total_amount_paid'] or 0),
                        'total_balance': float(orders_summary['total_balance'] or 0)
                    },
                    'expenses_breakdown': {
                        'total_expenses': float(expenses_summary['total_expenses'] or 0),
                        'total_expense_records': expenses_summary['expenses_count'] or 0
                    },
                    'order_items_breakdown': {
                        'total_items_value': float(order_items_summary['total_items_value'] or 0),
                        'total_items_quantity': order_items_summary['total_items_count'] or 0,
                        'distinct_item_entries': order_items_summary['distinct_items'] or 0
                    }
                },
                'detailed_breakdown': {
                    'revenue_by_shop': revenue_by_shop,
                    'expenses_by_shop': expenses_by_shop
                },
                'sample_data': {
                    'recent_orders': sample_orders,
                    'recent_expenses': sample_expenses
                },
                'calculations_verification': {
                    'revenue_minus_expenses': float(total_revenue - total_expenses),
                    'should_equal_net_profit': net_profit == (total_revenue - total_expenses),
                    'amount_paid_plus_balance_equals_total': (
                        float((orders_summary['total_amount_paid'] or 0) + (orders_summary['total_balance'] or 0)) == 
                        float(total_revenue)
                    )
                },
                'database_counts': {
                    'total_order_records': Order.objects.count(),
                    'total_expense_records': ExpenseRecord.objects.count(),
                    'total_order_item_records': OrderItem.objects.count(),
                    'total_customers': Customer.objects.count()
                }
            }
            
            return JsonResponse(response_data, json_dumps_params={'indent': 2})
            
        except Exception as e:
            error_response = {
                'status': 'error',
                'message': str(e),
                'error_type': type(e).__name__
            }
            return JsonResponse(error_response, status=500, json_dumps_params={'indent': 2})


# Alternative simpler version for quick debugging
def quick_financial_debug(request):
    """
    Quick debug endpoint that returns basic financial totals
    """
    try:
        # Basic aggregates
        total_revenue = Order.objects.aggregate(total=Sum('total_price'))['total'] or 0
        total_expenses = ExpenseRecord.objects.aggregate(total=Sum('amount'))['total'] or 0
        total_paid = Order.objects.aggregate(total=Sum('amount_paid'))['total'] or 0
        total_balance = Order.objects.aggregate(total=Sum('balance'))['total'] or 0
        
        # Counts
        order_count = Order.objects.count()
        expense_count = ExpenseRecord.objects.count()
        
        response_data = {
            'total_revenue': float(total_revenue),
            'total_expenses': float(total_expenses),
            'net_profit': float(total_revenue - total_expenses),
            'total_amount_paid': float(total_paid),
            'total_balance': float(total_balance),
            'order_count': order_count,
            'expense_count': expense_count,
            'verification': {
                'revenue_equals_paid_plus_balance': float(total_revenue) == float(total_paid + total_balance),
                'difference': float(total_revenue) - float(total_paid + total_balance)
            }
        }
        
        return JsonResponse(response_data, json_dumps_params={'indent': 2})
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# View to check individual order calculations
def debug_order_calculations(request):
    """
    Debug view to check if order calculations are correct
    """
    try:
        orders_with_issues = []
        correct_orders = 0
        
        # Check each order's calculations
        for order in Order.objects.all().prefetch_related('items'):
            # Calculate what the total should be based on items
            calculated_total = sum(float(item.total_item_price) for item in order.items.all())
            stored_total = float(order.total_price)
            
            # Calculate what balance should be
            calculated_balance = stored_total - float(order.amount_paid)
            stored_balance = float(order.balance)
            
            # Check for discrepancies
            total_matches = abs(calculated_total - stored_total) < 0.01  # Allow for floating point errors
            balance_matches = abs(calculated_balance - stored_balance) < 0.01
            
            if not total_matches or not balance_matches:
                orders_with_issues.append({
                    'order_code': order.uniquecode,
                    'calculated_total': calculated_total,
                    'stored_total': stored_total,
                    'total_difference': calculated_total - stored_total,
                    'amount_paid': float(order.amount_paid),
                    'calculated_balance': calculated_balance,
                    'stored_balance': stored_balance,
                    'balance_difference': calculated_balance - stored_balance,
                    'item_count': order.items.count()
                })
            else:
                correct_orders += 1
        
        response_data = {
            'total_orders_checked': Order.objects.count(),
            'correct_orders': correct_orders,
            'orders_with_calculation_issues': len(orders_with_issues),
            'issues_found': orders_with_issues,
            'issue_summary': {
                'total_mismatch_count': len([o for o in orders_with_issues if abs(o['total_difference']) >= 0.01]),
                'balance_mismatch_count': len([o for o in orders_with_issues if abs(o['balance_difference']) >= 0.01])
            }
        }
        
        return JsonResponse(response_data, json_dumps_params={'indent': 2})
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
