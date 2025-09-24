from decimal import Decimal
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
    """Edit an existing order"""
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
                    # Save customer
                    customer_form.save()
                    
                    # Save order
                    updated_order = order_form.save(commit=False)
                    updated_order.save()
                    
                    # Handle order items - delete existing and create new ones
                    order.items.all().delete()
                    for form in item_formset:
                        if form.cleaned_data and not form.cleaned_data.get('DELETE', False):
                            order_item = form.save(commit=False)
                            order_item.order = updated_order
                            order_item.save()
                    
                    # Recalculate total price
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

from decimal import Decimal, InvalidOperation
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required

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
@shop_required
def search_customers(request):
    """API endpoint to search for customers by phone or name"""
    if request.method == 'GET':
        query = request.GET.get('q', '').strip()
        
        if len(query) < 2:
            return JsonResponse({'customers': []})
        
        # Base queryset
        customers = Customer.objects.filter(
            Q(phone__icontains=query) | Q(name__icontains=query)
        )
        
        # Apply permission filtering
        customers = apply_customer_permissions(customers, request)
        
        # Apply the limit AFTER all filtering
        customers = customers[:10]  # Limit to 10 results
        
        results = []
        for customer in customers:
            results.append({
                'id': customer.id,
                'name': customer.name,
                'phone': str(customer.phone),  # Convert PhoneNumber to string
                'address': customer.address,
            })
        
        return JsonResponse({'customers': results})
    
    return JsonResponse({'error': 'Invalid request'}, status=400)

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





def get_hotel_financial_summary():
    # ✅ Calculate total revenue
    #HOTEL PROFIT
    revenue = OrderItem.objects.aggregate(
        total=Coalesce(
            Sum(F('quantity') * F('food_item__price'), output_field=DecimalField()),
            0
        )
    )['total']

    # ✅ Calculate total expenses
    expenses = HotelExpenseRecord.objects.aggregate(
        total=Coalesce(Sum('amount'), 0)
    )['total']

    # ✅ Profit = Revenue - Expenses
    profit = revenue - expenses

    return {
        'revenue': revenue,
        'expenses': expenses,
        'profit': profit
    }

# OR: from datetime import datetime
from django.db.models import Sum, F, DecimalField
from django.db.models.functions import Coalesce
from django.utils.timezone import now
import logging

logger = logging.getLogger(__name__)


def get_laundry_profit_and_hotel(request, selected_year=None):
    """
    Get the total profit for both laundry and hotel businesses
    """
    try:
        # HOTEL PROFIT CALCULATION
        from HotelApp.models import HotelOrderItem, HotelExpenseRecord
        
        # Calculate hotel revenue by iterating through order items
        hotel_revenue = Decimal('0.00')
        for order_item in HotelOrderItem.objects.select_related('food_item').all():
            if order_item.food_item and order_item.food_item.price:
                hotel_revenue += Decimal(str(order_item.quantity)) * Decimal(str(order_item.food_item.price))
        
        # Calculate hotel expenses
        hotel_expenses_result = HotelExpenseRecord.objects.aggregate(
            total=Sum('amount')
        )
        hotel_expenses = Decimal(str(hotel_expenses_result['total'] or '0.00'))
        
        hotel_profit = hotel_revenue - hotel_expenses
        
        # LAUNDRY PROFIT CALCULATION
        from .analytics import DashboardAnalytics
        
        analytics = DashboardAnalytics(None)
        
        if selected_year is None:
            selected_year = now().year
            
        laundry_data = analytics.get_dashboard_data(request, selected_year)
        
        # Extract laundry revenue and expenses
        laundry_revenue = Decimal(str(laundry_data.get('order_stats', {}).get('total_revenue', 0) or 0))
        laundry_expenses = Decimal(str(laundry_data.get('expense_stats', {}).get('total_expenses', 0) or 0))
        laundry_profit = laundry_revenue - laundry_expenses
        
        # TOTALS
        total_revenue = hotel_revenue + laundry_revenue
        total_profit = hotel_profit + laundry_profit
        
        # Convert to float for template (or keep as Decimal if your template filters support it)
        context = {
            'total_revenue': float(total_revenue),
            'laundry_profit': float(laundry_profit),
            'hotel_profit': float(hotel_profit),
            'total_profit': float(total_profit),
        }
        
        return render(request, 'Admin/Generaldashboard.html', context)
        
    except Exception as e:
        logger.error(f"Error in get_laundry_profit_and_hotel: {e}")
        context = {
            'total_revenue': 0,
            'laundry_profit': 0,
            'hotel_profit': 0,
            'total_profit': 0,
        }
        return render(request, 'Admin/Generaldashboard.html', context)

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
            messages.warning(request, f"Order {order.uniquecode} is already fully paid.")
            return redirect('laundry:customordertable')
            
        cl = MpesaClient()
        phone_number = str(order.customer.phone)
        amount = int(order.balance)  # This should be the exact balance amount
        
        account_reference = f"ORDER{order.id}"
        transaction_desc = f"Payment for order {order.uniquecode}"
        callback_url = 'https://mydomain.com/path'
        # Use a valid callback URL - make sure this matches your actual domain
        #callback_url = request.build_absolute_uri(reverse('stk_push_callback'))
        
        try:
            response = cl.stk_push(phone_number, amount, account_reference, transaction_desc, callback_url)
            response_data = response.json()
            
            if 'CheckoutRequestID' in response_data:
                checkout_request_id = response_data['CheckoutRequestID']
                order.checkout_request_id = checkout_request_id
                order.payment_status = 'processing'  # Set status to processing while waiting for callback
                order.save()
                
                messages.success(request, f"Payment initiated for order {order.uniquecode}. Check your phone to complete payment.")
            else:
                error_message = response_data.get('errorMessage', 'Unknown error occurred')
                messages.error(request, f"Payment initiation failed: {error_message}")
                
        except Exception as e:
            logger.error(f"Error initiating payment: {e}")
            messages.error(request, f"Error initiating payment: {str(e)}")
            
        return redirect('laundry:customordertable')
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'})

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

@login_required
def user_add(request):
    if request.method == 'POST':
        form = UserCreateForm(request.POST)
        profile_form = ProfileEditForm(request.POST)
        laundry_form = LaundryProfileForm(request.POST)

        if form.is_valid() and profile_form.is_valid():
            try:
                with transaction.atomic():
                    # Create base user object but don't save yet
                    user = form.save(commit=False)

                    # Get profile data
                    user_type = profile_form.cleaned_data['user_type']
                    app_type = profile_form.cleaned_data['app_type']

                    # ✅ Assign role permissions
                    if user_type == "admin":
                        user.is_staff = True
                        user.is_superuser = True   # <-- allow superuser even for laundry
                    elif user_type == "staff":
                        user.is_staff = True
                        user.is_superuser = False
                    else:
                        user.is_staff = False
                        user.is_superuser = False

                    user.user_type = user_type
                    user.app_type = app_type
                    user.save()

                    # ✅ Enforce Laundry shop assignment for staff only
                    if app_type == 'laundry' and not user.is_superuser:
                        if laundry_form.is_valid():
                            laundry_profile = laundry_form.save(commit=False)
                            laundry_profile.user = user
                            laundry_profile.save()
                        else:
                            messages.error(request, f"Laundry form errors: {laundry_form.errors}")
                            raise Exception("Please select a valid shop for laundry users.")

                    elif app_type == 'hotel':
                        # Add HotelProfile logic if needed
                        pass

                messages.success(request, f"User {user.email} created successfully!")
                return redirect('laundry:user_management')

            except IntegrityError:
                form.add_error("email", "This email is already registered.")
            except Exception as e:
                messages.error(request, f"Error creating user: {str(e)}")

    else:
        form = UserCreateForm()
        profile_form = ProfileEditForm()
        laundry_form = LaundryProfileForm()

    return render(request, "Admin/user_form.html", {
        "form": form,
        "profile_form": profile_form,
        "laundry_form": laundry_form,
        "title": "Add New User"
    })


@login_required
@admin_required
def user_edit(request, pk):
    """Edit user information including profile and laundry profile"""
    user = get_object_or_404(User, pk=pk)

    # Get laundry profile if exists
    laundry_profile = getattr(user, 'laundry_profile', None)

    if request.method == 'POST':
        user_form = UserEditForm(request.POST, instance=user, prefix='user')
        laundry_form = LaundryProfileForm(
            request.POST, 
            instance=laundry_profile, 
            prefix='laundry'
        )
        password_form = PasswordChangeForm(user, request.POST, prefix='password')

        # Save user + (optional) laundry profile
        if 'update_user' in request.POST:
            forms_valid = user_form.is_valid()

            if forms_valid and user_form.cleaned_data.get('app_type') == 'laundry':
                forms_valid = laundry_form.is_valid()

            if forms_valid:
                try:
                    with transaction.atomic():
                        user = user_form.save(commit=False)

                        # Handle staff/admin permissions
                        if user.user_type == 'admin':
                            user.is_staff = True
                            user.is_superuser = True
                        elif user.user_type == 'staff':
                            user.is_staff = True
                            user.is_superuser = False
                        else:
                            user.is_staff = False
                            user.is_superuser = False

                        user.save()

                        # Handle laundry profile
                        if user.app_type == 'laundry':
                            laundry_profile = laundry_form.save(commit=False)
                            laundry_profile.user = user
                            laundry_profile.save()
                        elif hasattr(user, 'laundry_profile'):
                            user.laundry_profile.delete()

                    messages.success(request, f'User {user.username} updated successfully!')
                    return redirect('laundry:user_management')

                except Exception as e:
                    messages.error(request, f'Error updating user: {str(e)}')

        elif 'change_password' in request.POST and password_form.is_valid():
            password_form.save()
            if request.user == user:
                update_session_auth_hash(request, user)
            messages.success(request, 'Password updated successfully!')
            return redirect('laundry:user_edit', pk=user.pk)

    else:
        user_form = UserEditForm(instance=user, prefix='user')
        password_form = PasswordChangeForm(user, prefix='password')

        if hasattr(user, 'laundry_profile'):
            laundry_form = LaundryProfileForm(instance=user.laundry_profile, prefix='laundry')
        else:
            laundry_form = LaundryProfileForm(prefix='laundry')

    context = {
        'user_form': user_form,
        'laundry_form': laundry_form,
        'password_form': password_form,
        'user': user,
        'title': f'Edit User - {user.username}'
    }

    return render(request, 'Admin/user_edit_form.html', context)

@login_required
@admin_required
def user_profile(request, pk):
    """View user profile and details with laundry profile information"""
    user = get_object_or_404(User, pk=pk)
    laundry_profile = getattr(user, 'laundryprofile', None)
    
    # Get customers created by this user
    customers_created = Customer.objects.filter(created_by=user).count()
    
    # Get orders for customers created by this user
    customers = Customer.objects.filter(created_by=user)
    user_orders = Order.objects.filter(customer__in=customers)
    
    total_orders = user_orders.count()
    total_revenue = user_orders.aggregate(total=Sum('total_price'))['total'] or 0
    
    context = {
        'user': user,
        'laundry_profile': laundry_profile,
        'total_orders': total_orders,
        'total_revenue': total_revenue,
        'customers_created': customers_created,
    }
    
    return render(request, 'Admin/user_profile.html', context)

@login_required
@admin_required
def user_management(request):
    """Optimized User management page for admins with laundry shop information"""

    # Start with all users
    users = User.objects.all()

    # --- Filters ---
    search_query = request.GET.get("search", "").strip()
    shop_filter = request.GET.get("shop", "").strip()
    status_filter = request.GET.get("status", "").strip()
    user_type_filter = request.GET.get("user_type", "").strip()
    app_type_filter = request.GET.get("app_type", "").strip()

    if search_query:
        users = users.filter(
            Q(email__icontains=search_query)
            | Q(first_name__icontains=search_query)
            | Q(last_name__icontains=search_query)
        )

    if shop_filter:
        users = users.filter(laundry_profile__shop=shop_filter)

    if status_filter:
        status_map = {
            "active": {"is_active": True},
            "inactive": {"is_active": False},
            "staff": {"is_staff": True},
            "superuser": {"is_superuser": True},
        }
        if status_filter in status_map:
            users = users.filter(**status_map[status_filter])

    if user_type_filter:
        users = users.filter(user_type=user_type_filter)

    if app_type_filter:
        users = users.filter(app_type=app_type_filter)

    # --- Build options for filters ---
    all_shops = (
        LaundryProfile.objects.values_list("shop", flat=True).distinct().order_by("shop")
    )
    shop_options = [{"value": "", "label": "All Shops", "selected": shop_filter == ""}]
    shop_options += [
        {"value": shop, "label": shop, "selected": shop_filter == shop}
        for shop in all_shops
    ]

    status_options = [
        {"value": "", "label": "All Status", "selected": status_filter == ""},
        {"value": "active", "label": "Active", "selected": status_filter == "active"},
        {"value": "inactive", "label": "Inactive", "selected": status_filter == "inactive"},
        {"value": "staff", "label": "Staff Users", "selected": status_filter == "staff"},
        {"value": "superuser", "label": "Superusers", "selected": status_filter == "superuser"},
    ]

    user_type_options = [
        {"value": "", "label": "All Types", "selected": user_type_filter == ""},
        {"value": "admin", "label": "Admins", "selected": user_type_filter == "admin"},
        {"value": "staff", "label": "Staff", "selected": user_type_filter == "staff"},
        {"value": "customer", "label": "Customers", "selected": user_type_filter == "customer"},
    ]

    app_type_options = [
        {"value": "", "label": "All App Types", "selected": app_type_filter == ""},
        {"value": "laundry", "label": "Laundry", "selected": app_type_filter == "laundry"},
        {"value": "hotel", "label": "Hotel", "selected": app_type_filter == "hotel"},
    ]

    # --- Prepare user details ---
    users_with_status = []
    for user in users:
        # Account status
        if not user.is_active:
            status = ("inactive", "danger", "Inactive")
        elif user.is_superuser:
            status = ("superuser", "primary", "Superuser")
        elif user.is_staff:
            status = ("staff", "info", "Staff")
        else:
            status = ("active", "success", "Active")

        # Login info
        if user.last_login:
            last_login = user.last_login.strftime("%Y-%m-%d %H:%M")
            days_since_login = (timezone.now() - user.last_login).days
        else:
            last_login = "Never"
            days_since_login = None

        # Add full details
        users_with_status.append(
            {
                "id": user.id,
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "is_active": user.is_active,
                "is_staff": user.is_staff,
                "is_superuser": user.is_superuser,
                "status": status[0],
                "status_class": status[1],
                "status_text": status[2],
                "last_login": last_login,
                "days_since_login": days_since_login,
                "user_type": getattr(user, "user_type", ""),
                "app_type": getattr(user, "app_type", ""),
                "shop": getattr(getattr(user, "laundry_profile", None), "shop", ""),
                "is_online": bool(
                    user.last_login
                    and (timezone.now() - user.last_login).seconds < 300
                ),
                "date_joined": user.date_joined.strftime("%Y-%m-%d"),
            }
        )

    # --- Pagination ---
    paginator = Paginator(users_with_status, 20)
    page_number = request.GET.get("page")
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    # --- Statistics ---
    total_users = users.count()
    active_users = users.filter(is_active=True).count()
    inactive_users = users.filter(is_active=False).count()
    staff_users = users.filter(is_staff=True, is_superuser=False).count()
    superusers = users.filter(is_superuser=True).count()
    never_logged_in = users.filter(last_login__isnull=True).count()
    recently_active = users.filter(last_login__gte=timezone.now() - timezone.timedelta(days=7)).count()

    # --- Context ---
    context = {
        "users": page_obj,
        "search_query": search_query,
        "shop_options": shop_options,
        "status_options": status_options,
        "user_type_options": user_type_options,
        "app_type_options": app_type_options,
        "total_users": total_users,
        "active_users": active_users,
        "inactive_users": inactive_users,
        "staff_users": staff_users,
        "superusers": superusers,
        "never_logged_in": never_logged_in,
        "recently_active": recently_active,
        "current_filters": {
            "shop": shop_filter,
            "status": status_filter,
            "user_type": user_type_filter,
            "app_type": app_type_filter,
        },
    }

    return render(request, "Admin/user_management.html", context)

@login_required
@admin_required
def user_delete(request, pk):
    """Delete a user"""
    user = get_object_or_404(User, pk=pk)
    
    # Prevent users from deleting themselves
    if user == request.user:
        messages.error(request, "You cannot delete your own account!")
        return redirect('laundry:user_management')
    
    if request.method == 'POST':
        email = user.email
        user.delete()
        messages.success(request, f'User {email} deleted successfully!')
        return redirect('laundry:user_management')
    
    context = {
        'user': user,
    }
    
    return render(request, 'Admin/user_confirm_delete.html', context)

@login_required
@shop_required
def customer_management(request):
    """Customer management page with search and filtering"""
    customers = Customer.objects.annotate(
        order_count=Count('orders'),
        total_spent=Sum('orders__total_price')
    ).order_by('-id')
    
    # Search functionality
    search_query = request.GET.get('search', '')
    if search_query:
        customers = customers.filter(
            Q(name__icontains=search_query) |
            Q(phone__icontains=search_query)
        )
    
    # Apply permission filtering
    customers = apply_customer_permissions(customers, request)
    
    # Also include customers created by users from the same shop
    user_shops = get_user_shops(request)
    if user_shops is not None and user_shops and not request.user.is_superuser:
        # Get users from the same shops
        same_shop_user_ids = User.objects.filter(
            laundry_profile__shop__in=user_shops
        ).values_list('id', flat=True)
        
        # Include customers created by users from the same shop
        same_shop_customers = Customer.objects.filter(
            created_by_id__in=same_shop_user_ids
        )
        
        # Combine with existing customers
        customers = customers | same_shop_customers
        customers = customers.distinct()
    
    # Pagination
    paginator = Paginator(customers, 20)
    page_number = request.GET.get('page')
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)
    
    context = {
        'customers': page_obj,
        'search_query': search_query,
        'total_customers': customers.count(),
    }
    
    return render(request, 'Admin/customer_management.html', context)

@login_required
@shop_required
def customer_add(request):
    """Add new customer"""
    if request.method == 'POST':
        form = CustomerForm(request.POST)
        if form.is_valid():
            customer = form.save(commit=False)
            customer.created_by = request.user
            customer.save()
            messages.success(request, f'Customer {customer.name} added successfully!')
            return redirect('laundry:customer_management')
    else:
        form = CustomerForm()
    
    context = {
        'form': form,
        'title': 'Add New Customer'
    }
    
    return render(request, 'Admin/customer_form.html', context)

@login_required
@shop_required
def customer_edit(request, pk):
    """Edit customer information"""
    customer = get_object_or_404(Customer, pk=pk)
    
    # Check if user has permission to edit this customer
    if not check_customer_permission(request, customer):
        messages.error(request, "You don't have permission to edit this customer.")
        return redirect('laundry:customer_management')
    
    if request.method == 'POST':
        form = CustomerForm(request.POST, instance=customer)
        if form.is_valid():
            form.save()
            messages.success(request, f'Customer {customer.name} updated successfully!')
            return redirect('laundry:customer_management')
    else:
        form = CustomerForm(instance=customer)
    
    context = {
        'form': form,
        'customer': customer,
        'title': f'Edit Customer - {customer.name}'
    }
    
    return render(request, 'Admin/customer_form.html', context)

@login_required
@shop_required
def customer_delete(request, pk):
    """Delete a customer (only if they have no orders)"""
    customer = get_object_or_404(Customer, pk=pk)
    
    # Check if user has permission
    if not check_customer_permission(request, customer):
        messages.error(request, "You don't have permission to delete this customer.")
        return redirect('laundry:customer_management')
    
    if request.method == 'POST':
        # Check if customer has orders
        if customer.orders.exists():
            messages.error(request, f'Cannot delete {customer.name} because they have existing orders.')
            return redirect('laundry:customer_management')
        
        customer_name = customer.name
        customer.delete()
        messages.success(request, f'Customer {customer_name} deleted successfully!')
        return redirect('laundry:customer_management')
    
    context = {
        'customer': customer,
    }
    
    return render(request, 'Admin/customer_confirm_delete.html', context)

@login_required
@shop_required
def customer_orders(request, pk):
    """View all orders for a specific customer"""
    customer = get_object_or_404(Customer, pk=pk)
    
    # Check permission
    if not check_customer_permission(request, customer):
        messages.error(request, "You don't have permission to view this customer's orders.")
        return redirect('laundry:customer_management')
    
    # Get orders for this customer
    orders = customer.orders.all()
    
    # Apply order permissions
    orders = apply_order_permissions(orders, request)
    
    # Get statistics
    total_orders = orders.count()
    total_spent = orders.aggregate(total=Sum('total_price'))['total'] or 0
    avg_order_value = total_spent / total_orders if total_orders > 0 else 0
    
    # Pagination
    paginator = Paginator(orders, 15)
    page_number = request.GET.get('page')
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)
    
    context = {
        'customer': customer,
        'orders': page_obj,
        'total_orders': total_orders,
        'total_spent': total_spent,
        'avg_order_value': avg_order_value,
    }
    
    return render(request, 'Admin/customer_orders.html', context) 


@login_required
def create_expense_field(request):
    default_expenses = [
        "Electricity Token",
        "Soap",
        "Softener",
        "Bleach",
        "Stain removers",
        "Laundry Bags",
        "Hangers",
        "Laundry Starch",
        "Rent",
        "Salaries",
        "Delivery fees",
        "Tags",
        "Machine service fee",
    ]

    if request.method == "POST":
        # Case 1: Create default categories (for single business)
        if 'create_defaults' in request.POST:
            created_count = 0
            for label in default_expenses:
                obj, created = ExpenseField.objects.get_or_create(label=label)
                if created:
                    created_count += 1

            if created_count > 0:
                messages.success(request, f"Successfully created {created_count} default expense categories!")
            else:
                messages.info(request, "All default expense categories already exist.")

            return redirect("laundry:expense_field_list")

        # Case 2: Manual form submission
        form = ExpenseFieldForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Expense field created successfully!")
            return redirect("laundry:expense_field_list")
    else:
        form = ExpenseFieldForm()

    return render(request, "expenses/create_expense_field.html", {
        "form": form,
        "default_expenses": default_expenses
    })


@login_required
def expense_field_list(request):
    fields = ExpenseField.objects.all()
    return render(request, "expenses/expense_field_list.html", {"fields": fields})


@login_required
def edit_expense_field(request, field_id):
    field = get_object_or_404(ExpenseField, id=field_id)
    if request.method == "POST":
        form = ExpenseFieldForm(request.POST, instance=field)
        if form.is_valid():
            form.save()
            messages.success(request, "Expense field updated successfully!")
            return redirect("laundry:expense_field_list")
    else:
        form = ExpenseFieldForm(instance=field)
    return render(request, "expenses/edit_expense_field.html", {"form": form, "field": field})


@login_required
def delete_expense_field(request, field_id):
    field = get_object_or_404(ExpenseField, id=field_id)
    if request.method == "POST":
        field.delete()
        messages.success(request, "Expense field deleted successfully!")
        return redirect("laundry:expense_field_list")
    return render(request, "expenses/delete_expense_field.html", {"field": field})


# views.py - Update expense_form view
@login_required
@shop_required
def expense_form(request):
    user_shops = get_user_shops(request)

    if request.method == "POST":
        form = ExpenseRecordForm(request.POST)

        if form.is_valid():
            expense_record = form.save(commit=False)

            # Auto-assign shop based on user type
            if request.user.is_superuser:
                # For superuser, check if shop is provided in form data
                shop = request.POST.get('shop')
                if shop:
                    expense_record.shop = shop
                else:
                    # If no shop provided, use the first available shop or show error
                    if user_shops and len(user_shops) == 1:
                        expense_record.shop = user_shops[0]
                    else:
                        messages.error(request, "Please select a shop for this expense.")
                        context = {
                            "form": form,
                            "user_shop": user_shops[0] if user_shops else '',
                            "is_superuser": request.user.is_superuser,
                        }
                        return render(request, "expenses/expense_form.html", context)
            else:
                # Staff user - auto-assign their shop
                if user_shops and len(user_shops) == 1:
                    expense_record.shop = user_shops[0]
                else:
                    messages.error(request, "Unable to determine your shop assignment.")
                    return redirect("laundry:expense_list")

            expense_record.save()
            messages.success(request, "Expense recorded successfully!")
            return redirect("laundry:expense_list")
    else:
        form = ExpenseRecordForm()

    context = {
        "form": form,
        "user_shop": user_shops[0] if user_shops else '',
        "is_superuser": request.user.is_superuser,
    }
    return render(request, "expenses/expense_form.html", context)

@login_required
def expense_list(request):
    records = ExpenseRecord.objects.select_related("field").order_by("-date")

    # Calculate stats for the cards
    total_amount = records.aggregate(Sum('amount'))['amount__sum'] or 0
    record_count = records.count()
    average_expense = records.aggregate(Avg('amount'))['amount__avg'] or 0

    context = {
        "records": records,
        "total_amount": total_amount,
        "record_count": record_count,
        "average_expense": round(average_expense, 2),
    }
    return render(request, "expenses/expense_list.html", context)


@login_required
def edit_expense_record(request, record_id):
    record = get_object_or_404(ExpenseRecord, id=record_id)
    if request.method == "POST":
        form = ExpenseRecordForm(request.POST, instance=record)
        if form.is_valid():
            form.save()
            messages.success(request, "Expense record updated successfully!")
            return redirect("laundry:expense_list")
    else:
        form = ExpenseRecordForm(instance=record)
    return render(request, "expenses/edit_expense_record.html", {"form": form, "record": record})


@login_required
def delete_expense_record(request, record_id):
    record = get_object_or_404(ExpenseRecord, id=record_id)
    if request.method == "POST":
        record.delete()
        messages.success(request, "Expense record deleted successfully!")
        return redirect("laundry:expense_list")
    return render(request, "expenses/delete_expense_record.html", {"record": record})

@login_required
def debug_users(request):
    """Return all user data as JSON for debugging."""
    users = User.objects.all().values(
        "id",
        "email",
        "first_name",
        "last_name",
        "user_type",   # custom field in UserProfile
        "app_type",    # custom field in UserProfile
        "is_staff",
        "is_superuser",
        "is_active",
        "last_login",
        "date_joined",
    )
    return JsonResponse(list(users), safe=False)