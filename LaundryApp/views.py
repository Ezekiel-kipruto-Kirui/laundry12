from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django_daraja.mpesa.core import MpesaClient
import json
import logging
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
from django.db.models import Q, Prefetch, Sum, Count, Avg
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from django.db import IntegrityError
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth import update_session_auth_hash


# Local imports
from .models import Customer, Order, OrderItem, UserProfile,ExpenseField, ExpenseRecord
from .forms import CustomerForm, OrderForm, OrderItemForm, UserEditForm, UserCreateForm, ProfileEditForm,ExpenseFieldForm, ExpenseRecordForm

from .resource import OrderResource
from .analytics import DashboardAnalytics

# Setup logger
logger = logging.getLogger(__name__)

# Constants
SHOP_A = 'Shop A'
SHOP_B = 'Shop B'

# Cached functions and reusable queries
def get_user_shops(request):
    """Get the shops associated with the current user based on profile"""
    if request.user.is_superuser:
        return None  # Superusers can access all shops
    
    try:
        profile = request.user.profile
        if profile.shop:
            return [profile.shop]
    except UserProfile.DoesNotExist:
        pass
    
    return []

def is_admin(user):
    return (user.is_superuser or 
            (hasattr(user, 'profile') and user.profile.user_type == 'admin'))

def is_staff(user):
    return (user.is_staff or 
            (hasattr(user, 'profile') and user.profile.user_type in ['admin', 'staff']))

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
            return redirect('dashboard')
        return view_func(request, *args, **kwargs)
    return _wrapped_view

def staff_required(view_func):
    """Decorator to ensure user is staff"""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not is_staff(request.user):
            messages.error(request, "You don't have staff privileges.")
            return redirect('dashboard')
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

def apply_order_permissions(queryset, request):
    """Apply permission-based filtering to order queryset"""
    user_shops = get_user_shops(request)
    
    if user_shops is not None:  # Not superuser
        if user_shops:  # User has shop assignments
            queryset = queryset.filter(shop__in=user_shops)
        else:  # User has no shop assignments
            queryset = queryset.none()
    
    # For staff users, only show orders they created
    if (hasattr(request.user, 'profile') and 
        request.user.profile.user_type == 'staff' and 
        not request.user.is_superuser):
        queryset = queryset.filter(created_by=request.user)
    
    return queryset

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

    # Initialize DashboardAnalytics with a mock admin instance
    class MockAdmin:
        def get_user_shops(self, request):
            return get_user_shops(request)
    
    mock_admin = MockAdmin()
    analytics = DashboardAnalytics(mock_admin)
    
    # Get dashboard data using the analytics class
    data = analytics.get_dashboard_data(request, selected_year, selected_month)
    
    # Prepare context using the analytics class
    context = analytics.prepare_dashboard_context(request, data, selected_year, selected_month)
    
    # Add any additional context you need
    context.update({
        'selected_year': selected_year,
        'selected_month': selected_month,
    })
    
    return render(request, 'Admin/reports.html', context)

@login_required
@shop_required
def customordertable(request):
    # Start with base queryset - exclude delivered orders from the main query
    orders = get_base_order_queryset().exclude(order_status='delivered')

    # Make sure we're not including orders without uniquecode
    orders = orders.exclude(uniquecode__isnull=True).exclude(uniquecode='')

    # Apply permission filtering
    orders = apply_order_permissions(orders, request)

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
            Q(items__itemname__icontains=search_query) 
        ).distinct()

    # Check if export was requested
    export_format = request.GET.get('export', '')
    if export_format:
        dataset = OrderResource().export(queryset=orders)
        
        if export_format == 'csv':
            response = HttpResponse(dataset.csv, content_type='text/csv')
            response['Content-Disposition'] = 'attachment; filename="orders_export_{}.csv"'.format(
                timezone.now().strftime('%Y-%m-%d_%H-%M-%S')
            )
            return response
            
        elif export_format == 'xlsx':
            # Proper way to handle Excel export
            xlsx_data = dataset.export('xlsx')
            response = HttpResponse(
                xlsx_data, 
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
            response['Content-Disposition'] = 'attachment; filename="orders_export_{}.xlsx"'.format(
                timezone.now().strftime('%Y-%m-%d_%H-%M-%S')
            )
            return response

    # Order by creation date
    orders = orders.order_by('-created_at')

    # Pagination
    paginator = Paginator(orders, 15)
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

@login_required
@shop_required
def order_detail(request, order_code):
    """View detailed information about a specific order"""
    try:
        order = get_base_order_queryset().get(uniquecode=order_code)
        
        # Check if user has permission to view this order
        user_shops = get_user_shops(request)
        if user_shops is not None and user_shops:  # Not superuser
            if order.shop not in user_shops:
                raise Http404("You don't have permission to view this order.")
        
        # For staff users, check if they created this order
        if (hasattr(request.user, 'profile') and 
            request.user.profile.user_type == 'staff' and 
            not request.user.is_superuser and
            order.created_by != request.user):
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
        user_shops = get_user_shops(request)
        if user_shops is not None and user_shops:  # Not superuser
            if order.shop not in user_shops:
                messages.error(request, "You don't have permission to edit this order.")
                return redirect('customordertable')
        
        # For staff users, check if they created this order
        if (hasattr(request.user, 'profile') and 
            request.user.profile.user_type == 'staff' and 
            not request.user.is_superuser and
            order.created_by != request.user):
            messages.error(request, "You don't have permission to edit this order.")
            return redirect('customordertable')
        
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
                    #updated_order.calculate_total_price()
                    updated_order.save()
                    
                    messages.success(request, f'Order {order.uniquecode} updated successfully!')
                    return redirect('customordertable')
                    
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
        order = Order.objects.only('uniquecode', 'shop', 'created_by').get(uniquecode=order_code)
        
        # Check if user has permission to delete this order
        user_shops = get_user_shops(request)
        if user_shops is not None and user_shops:  # Not superuser
            if order.shop not in user_shops:
                messages.error(request, "You don't have permission to delete this order.")
                return redirect('customordertable')
        
        # For staff users, check if they created this order
        if (hasattr(request.user, 'profile') and 
            request.user.profile.user_type == 'staff' and 
            not request.user.is_superuser and
            order.created_by != request.user):
            messages.error(request, "You don't have permission to delete this order.")
            return redirect('customordertable')
        
        if request.method == 'POST':
            order_code = order.uniquecode
            order.delete()
            messages.success(request, f'Order {order_code} deleted successfully!')
            return redirect('customordertable')
        
        context = {
            'order': order,
        }
        return render(request, 'Admin/order_confirm_delete.html', context)
        
    except Order.DoesNotExist:
        raise Http404("Order not found")

@login_required
@shop_required
@require_POST
def mark_order_completed(request, order_code):
    """Optimized mark order as completed"""
    order = get_object_or_404(Order, uniquecode=order_code)
    
    # Check permission
    user_shops = get_user_shops(request)
    if user_shops is not None and user_shops and order.shop not in user_shops:
        return JsonResponse({
            'success': False,
            'message': "You don't have permission to update this order."
        })
    
    # For staff users, check if they created this order
    if (hasattr(request.user, 'profile') and 
        request.user.profile.user_type == 'staff' and 
        not request.user.is_superuser and
        order.created_by != request.user):
        return JsonResponse({
            'success': False,
            'message': "You don't have permission to update this order."
        })
    
    # Ensure values are proper decimals before saving
    try:
        # Convert to Decimal if they are strings or other types
        if isinstance(order.total_price, str):
            order.total_price = Decimal(order.total_price)
        if isinstance(order.amount_paid, str):
            order.amount_paid = Decimal(order.amount_paid)
    except (TypeError, ValueError):
        # Handle conversion errors
        order.total_price = Decimal('0.00')
        order.amount_paid = Decimal('0.00')
    
    order.order_status = 'Completed'
    order.save()
    
    return JsonResponse({
        'success': True,
        'message': f'Order {order_code} marked as completed!'
    })

@login_required
@shop_required
def update_payment_status(request, order_code):
    """Update payment status of an order"""
    try:
        order = Order.objects.only('uniquecode', 'shop', 'created_by', 'total_price').get(uniquecode=order_code)
        
        # Check if user has permission to update this order
        user_shops = get_user_shops(request)
        if user_shops is not None and user_shops:  # Not superuser
            if order.shop not in user_shops:
                return JsonResponse({
                    'success': False,
                    'message': "You don't have permission to update this order."
                })
        
        # For staff users, check if they created this order
        if (hasattr(request.user, 'profile') and 
            request.user.profile.user_type == 'staff' and 
            not request.user.is_superuser and
            order.created_by != request.user):
            return JsonResponse({
                'success': False,
                'message': "You don't have permission to update this order."
            })
        
        if request.method == 'POST':
            payment_status = request.POST.get('payment_status')
            amount_paid = request.POST.get('amount_paid', 0)
            
            if payment_status in dict(Order.PAYMENT_STATUS_CHOICES).keys():
                order.payment_status = payment_status
                
                try:
                    order.amount_paid = float(amount_paid)
                    order.balance = float(order.total_price) - float(amount_paid)
                except (ValueError, TypeError):
                    order.balance = order.total_price - order.amount_paid
                
                order.save()
                
                return JsonResponse({
                    'success': True,
                    'message': f'Payment status updated to {payment_status}!'
                })
            else:
                return JsonResponse({
                    'success': False,
                    'message': 'Invalid payment status.'
                })
        
        return JsonResponse({
            'success': False,
            'message': 'Invalid request method.'
        })
        
    except Order.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'Order not found.'
        })

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
            post_data['shop'] = str(user_shops[0].id)  # Convert to string

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
                order.amount_paid = order.amount_paid or 0
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
                return redirect('customordertable')

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
            order_form.fields['shop'].initial = user_shops[0].id
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
        
        customers = Customer.objects.filter(
            Q(phone__icontains=query) | Q(name__icontains=query)
        )[:10]  # Limit to 10 results
        
        # Filter by shop if user is not superuser
        user_shops = get_user_shops(request)
        if user_shops is not None and user_shops:
            # Get orders from user's shops and then get those customers
            shop_customer_ids = Order.objects.filter(
                shop__in=user_shops
            ).values_list('customer_id', flat=True).distinct()
            customers = customers.filter(id__in=shop_customer_ids)
        
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
def generaldashboard(request):
    if not request.user.is_authenticated:
        return redirect('login')

    # Get user's shops
    user_shops = get_user_shops(request)

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
        
        # For staff users, only show orders they created
        if (hasattr(request.user, 'profile') and 
            request.user.profile.user_type == 'staff' and 
            not request.user.is_superuser):
            orders = orders.filter(created_by=request.user)
            count_orders = count_orders.filter(created_by=request.user)
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
    }
    return render(request, 'Admin/dashboard.html', context)

def dashboard(request):
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

def home(request):
    return render(request, 'home.html')

def index(request):
    cl = MpesaClient()
    phone_number = '0701396967'
    amount = 1
    account_reference = 'reference'
    transaction_desc = 'Description'
    callback_url = 'https://darajambili.herokuapp.com/express-payment'
    response = cl.stk_push(phone_number, amount, account_reference, transaction_desc, callback_url)
    return HttpResponse('Index')

@csrf_exempt
def stk_push_callback(request):
    """Handle M-Pesa STK Push callback"""
    if request.method == 'POST':
        # Process the callback data here
        data = json.loads(request.body)
        logger.info(f"STK Push callback received: {data}")
        return JsonResponse({'ResultCode': 0, 'ResultDesc': 'Success'})
    return JsonResponse({'ResultCode': 1, 'ResultDesc': 'Invalid request method'})

def logout_view(request):
    """Log out the current user and redirect to login page"""
    auth_logout(request)
    messages.info(request, "You have been successfully logged out.")
    return redirect('login')

@login_required
@admin_required
def user_management(request):
    """User management page for admins"""
    users = User.objects.select_related('profile').all().order_by('-date_joined')
    
    # Get filter parameters
    search_query = request.GET.get('search', '')
    shop_filter = request.GET.get('shop', '')
    status_filter = request.GET.get('status', '')
    user_type_filter = request.GET.get('user_type', '')
    
    # Apply filters
    if search_query:
        users = users.filter(
            Q(username__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query)
        )
    
    if shop_filter:
        users = users.filter(profile__shop=shop_filter)
    
    if status_filter == 'active':
        users = users.filter(is_active=True)
    elif status_filter == 'inactive':
        users = users.filter(is_active=False)
    elif status_filter == 'staff':
        users = users.filter(is_staff=True)
    elif status_filter == 'superuser':
        users = users.filter(is_superuser=True)
    
    if user_type_filter:
        users = users.filter(profile__user_type=user_type_filter)
    
    # Prepare filter options with selected status
    shop_options = [
        {'value': '', 'label': 'All Shops', 'selected': shop_filter == ''},
        {'value': 'Shop A', 'label': 'Shop A', 'selected': shop_filter == 'Shop A'},
        {'value': 'Shop B', 'label': 'Shop B', 'selected': shop_filter == 'Shop B'}
    ]
    
    status_options = [
        {'value': '', 'label': 'All Status', 'selected': status_filter == ''},
        {'value': 'active', 'label': 'Active', 'selected': status_filter == 'active'},
        {'value': 'inactive', 'label': 'Inactive', 'selected': status_filter == 'inactive'},
        {'value': 'staff', 'label': 'Staff Users', 'selected': status_filter == 'staff'},
        {'value': 'superuser', 'label': 'Superusers', 'selected': status_filter == 'superuser'}
    ]
    
    user_type_options = [
        {'value': '', 'label': 'All Types', 'selected': user_type_filter == ''},
        {'value': 'admin', 'label': 'Admins', 'selected': user_type_filter == 'admin'},
        {'value': 'staff', 'label': 'Staff', 'selected': user_type_filter == 'staff'}
    ]
    
    # Add last login information and account status to each user
    users_with_status = []
    for user in users:
        # Determine account status
        if not user.is_active:
            status = 'inactive'
            status_class = 'danger'
            status_text = 'Inactive'
        elif user.is_superuser:
            status = 'superuser'
            status_class = 'primary'
            status_text = 'Superuser'
        elif user.is_staff:
            status = 'staff'
            status_class = 'info'
            status_text = 'Staff'
        else:
            status = 'active'
            status_class = 'success'
            status_text = 'Active'
        
        # Get last login info
        if user.last_login:
            last_login = user.last_login.strftime('%Y-%m-%d %H:%M')
            days_since_login = (timezone.now() - user.last_login).days
        else:
            last_login = 'Never'
            days_since_login = None
        
        # Get user type from profile
        user_type = getattr(user.profile, 'user_type', 'N/A') if hasattr(user, 'profile') else 'N/A'
        shop = getattr(user.profile, 'shop', 'Not assigned') if hasattr(user, 'profile') else 'Not assigned'
        
        users_with_status.append({
            'user': user,
            'status': status,
            'status_class': status_class,
            'status_text': status_text,
            'last_login': last_login,
            'days_since_login': days_since_login,
            'user_type': user_type,
            'shop': shop,
            'is_online': user.last_login and (timezone.now() - user.last_login).seconds < 300  # Online if logged in last 5 minutes
        })
    
    # Pagination
    paginator = Paginator(users_with_status, 20)
    page_number = request.GET.get('page')
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)
    
    # Build pagination URL base
    pagination_params = []
    if search_query:
        pagination_params.append(f'search={search_query}')
    if shop_filter:
        pagination_params.append(f'shop={shop_filter}')
    if status_filter:
        pagination_params.append(f'status={status_filter}')
    if user_type_filter:
        pagination_params.append(f'user_type={user_type_filter}')
    
    pagination_url_suffix = '&'.join(pagination_params)
    if pagination_url_suffix:
        pagination_url_suffix = '&' + pagination_url_suffix
    
    # Statistics
    total_users = users.count()
    active_users = users.filter(is_active=True).count()
    inactive_users = users.filter(is_active=False).count()
    staff_users = users.filter(is_staff=True, is_superuser=False).count()
    superusers = users.filter(is_superuser=True).count()
    
    # Users who never logged in
    never_logged_in = users.filter(last_login__isnull=True).count()
    
    # Recently active users (last 7 days)
    seven_days_ago = timezone.now() - timezone.timedelta(days=7)
    recently_active = users.filter(last_login__gte=seven_days_ago).count()
    
    context = {
        'users': page_obj,
        'search_query': search_query,
        'shop_options': shop_options,
        'status_options': status_options,
        'user_type_options': user_type_options,
        'total_users': total_users,
        'active_users': active_users,
        'inactive_users': inactive_users,
        'staff_users': staff_users,
        'superusers': superusers,
        'never_logged_in': never_logged_in,
        'recently_active': recently_active,
        'pagination_url_suffix': pagination_url_suffix,
        'current_filters': {
            'shop': shop_filter,
            'status': status_filter,
            'user_type': user_type_filter
        }
    }
    
    return render(request, 'Admin/user_management.html', context)

@login_required
@admin_required
def user_add(request):
    """Add new user with proper validation"""
    if request.method == 'POST':
        form = UserCreateForm(request.POST)
        profile_form = ProfileEditForm(request.POST)

        if form.is_valid() and profile_form.is_valid():
            try:
                # Save the user
                user = form.save(commit=False)

                # Assign role based on profile user_type
                user_type = profile_form.cleaned_data.get("user_type")

                if user_type == "admin":
                    user.is_staff = True
                    user.is_superuser = True
                elif user_type == "staff":
                    user.is_staff = True
                    user.is_superuser = False

                user.save()

                # Create UserProfile
                profile = profile_form.save(commit=False)
                profile.user = user
                profile.save()

                messages.success(request, f'User {user.username} ({user_type}) created successfully!')
                return redirect('user_management')

            except Exception as e:
                messages.error(request, f'Error creating user: {str(e)}')
        else:
            # Collect all form errors
            error_messages = []
            for field, errors in {**form.errors, **profile_form.errors}.items():
                for error in errors:
                    error_messages.append(f"{field}: {error}")
            messages.error(request, 'Please correct the following errors: ' + '; '.join(error_messages))
    else:
        form = UserCreateForm()
        profile_form = ProfileEditForm()

    context = {
        'form': form,
        'profile_form': profile_form,
        'title': 'Add New User'
    }

    return render(request, 'Admin/user_form.html', context)

@login_required
@admin_required
def user_edit(request, pk):
    """Edit user information including profile and password"""
    user = get_object_or_404(User, pk=pk)
    
    # Get or create user profile
    profile, created = UserProfile.objects.get_or_create(user=user)
    
    if request.method == 'POST':
        user_form = UserEditForm(request.POST, instance=user, prefix='user')
        profile_form = ProfileEditForm(request.POST, instance=profile, prefix='profile')
        password_form = PasswordChangeForm(user, request.POST, prefix='password')
        
        # Check which form was submitted
        if 'update_user' in request.POST and user_form.is_valid() and profile_form.is_valid():
            try:
                # Save user information
                user = user_form.save(commit=False)
                
                # Update user type and permissions based on profile
                user_type = profile_form.cleaned_data.get('user_type')
                if user_type == 'admin':
                    user.is_staff = True
                    user.is_superuser = True
                elif user_type == 'staff':
                    user.is_staff = True
                    user.is_superuser = False
                
                user.save()
                
                # Save profile information
                profile = profile_form.save(commit=False)
                profile.user = user
                profile.save()
                
                messages.success(request, f'User {user.username} updated successfully!')
                return redirect('user_management')
                
            except Exception as e:
                messages.error(request, f'Error updating user: {str(e)}')
        
        elif 'change_password' in request.POST and password_form.is_valid():
            try:
                password_form.save()
                # Update the session auth hash to keep the user logged in if changing own password
                if request.user == user:
                    update_session_auth_hash(request, user)
                messages.success(request, 'Password updated successfully!')
                return redirect('user_edit', pk=user.pk)
                
            except Exception as e:
                messages.error(request, f'Error changing password: {str(e)}')
        
        else:
            # Collect all form errors
            error_messages = []
            if not user_form.is_valid():
                for field, errors in user_form.errors.items():
                    for error in errors:
                        error_messages.append(f"User {field}: {error}")
            
            if not profile_form.is_valid():
                for field, errors in profile_form.errors.items():
                    for error in errors:
                        error_messages.append(f"Profile {field}: {error}")
            
            if 'change_password' in request.POST and not password_form.is_valid():
                for field, errors in password_form.errors.items():
                    for error in errors:
                        error_messages.append(f"Password {field}: {error}")
            
            if error_messages:
                messages.error(request, 'Please correct the following errors: ' + '; '.join(error_messages))
    
    else:
        # GET request - initialize forms with current data
        user_form = UserEditForm(instance=user, prefix='user')
        profile_form = ProfileEditForm(instance=profile, prefix='profile')
        password_form = PasswordChangeForm(user, prefix='password')
    
    context = {
        'user_form': user_form,
        'profile_form': profile_form,
        'password_form': password_form,
        'user': user,
        'profile': profile,
        'title': f'Edit User - {user.username}'
    }
    
    return render(request, 'Admin/user_edit_form.html', context)

@login_required
@admin_required
def user_delete(request, pk):
    """Delete a user"""
    user = get_object_or_404(User, pk=pk)
    
    # Prevent users from deleting themselves
    if user == request.user:
        messages.error(request, "You cannot delete your own account!")
        return redirect('user_management')
    
    if request.method == 'POST':
        username = user.username
        user.delete()
        messages.success(request, f'User {username} deleted successfully!')
        return redirect('user_management')
    
    context = {
        'user': user,
    }
    
    return render(request, 'Admin/user_confirm_delete.html', context)



@login_required
@admin_required
def user_profile(request, pk):
    """View user profile and details"""
    user = get_object_or_404(User, pk=pk)
    profile = getattr(user, 'profile', None)
    
    # Get customers created by this user
    customers_created = Customer.objects.filter(created_by=user).count()
    
    # Get orders for customers created by this user
    customers = Customer.objects.filter(created_by=user)
    user_orders = Order.objects.filter(customer__in=customers)
    
    total_orders = user_orders.count()
    total_revenue = user_orders.aggregate(total=Sum('total_price'))['total'] or 0
    
    context = {
        'user': user,
        'profile': profile,
        'total_orders': total_orders,
        'total_revenue': total_revenue,
        'customers_created': customers_created,
    }
    
    return render(request, 'Admin/user_profile.html', context)

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
    
    # Filter by shop if user is not superuser
    user_shops = get_user_shops(request)
    if user_shops is not None and user_shops:
        # Get orders from user's shops and then get those customers
        shop_customer_ids = Order.objects.filter(
            shop__in=user_shops
        ).values_list('customer_id', flat=True).distinct()
        customers = customers.filter(id__in=shop_customer_ids)
    
    # For staff users, only show customers they created
    if (hasattr(request.user, 'profile') and 
        request.user.profile.user_type == 'staff' and 
        not request.user.is_superuser):
        customers = customers.filter(created_by=request.user)
    
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
            return redirect('customer_management')
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
    user_shops = get_user_shops(request)
    if user_shops is not None and user_shops:
        # Check if customer has orders in user's shops
        customer_shop_orders = Order.objects.filter(
            customer=customer,
            shop__in=user_shops
        ).exists()
        if not customer_shop_orders and not request.user.is_superuser:
            messages.error(request, "You don't have permission to edit this customer.")
            return redirect('customer_management')
    
    # For staff users, check if they created this customer
    if (hasattr(request.user, 'profile') and 
        request.user.profile.user_type == 'staff' and 
        not request.user.is_superuser and
        customer.created_by != request.user):
        messages.error(request, "You don't have permission to edit this customer.")
        return redirect('customer_management')
    
    if request.method == 'POST':
        form = CustomerForm(request.POST, instance=customer)
        if form.is_valid():
            form.save()
            messages.success(request, f'Customer {customer.name} updated successfully!')
            return redirect('customer_management')
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
    user_shops = get_user_shops(request)
    if user_shops is not None and user_shops:
        customer_shop_orders = Order.objects.filter(
            customer=customer,
            shop__in=user_shops
        ).exists()
        if not customer_shop_orders and not request.user.is_superuser:
            messages.error(request, "You don't have permission to delete this customer.")
            return redirect('customer_management')
    
    # For staff users, check if they created this customer
    if (hasattr(request.user, 'profile') and 
        request.user.profile.user_type == 'staff' and 
        not request.user.is_superuser and
        customer.created_by != request.user):
        messages.error(request, "You don't have permission to delete this customer.")
        return redirect('customer_management')
    
    if request.method == 'POST':
        # Check if customer has orders
        if customer.orders.exists():
            messages.error(request, f'Cannot delete {customer.name} because they have existing orders.')
            return redirect('customer_management')
        
        customer_name = customer.name
        customer.delete()
        messages.success(request, f'Customer {customer_name} deleted successfully!')
        return redirect('customer_management')
    
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
    user_shops = get_user_shops(request)
    orders = customer.orders.all()
    
    if user_shops is not None and user_shops and not request.user.is_superuser:
        orders = orders.filter(shop__in=user_shops)
        if not orders.exists():
            messages.error(request, "You don't have permission to view this customer's orders.")
            return redirect('customer_management')
    
    # For staff users, only show orders they created
    if (hasattr(request.user, 'profile') and 
        request.user.profile.user_type == 'staff' and 
        not request.user.is_superuser):
        orders = orders.filter(created_by=request.user)
    
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
    # Default expense categories
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
        "Machine service fee"
    ]
    
    if request.method == "POST":
        # Check if user wants to create default expenses
        if 'create_defaults' in request.POST:
            created_count = 0
            for expense_name in default_expenses:
                # Check if expense field already exists
                if not ExpenseField.objects.filter(label=expense_name).exists():
                    ExpenseField.objects.create(label=expense_name)
                    created_count += 1
            
            if created_count > 0:
                messages.success(request, f"Successfully created {created_count} default expense categories!")
            else:
                messages.info(request, "All default expense categories already exist.")
            
            return redirect("expense_field_list")
        
        # Process the regular form submission
        form = ExpenseFieldForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Expense field created successfully!")
            return redirect("expense_field_list")
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
            return redirect("expense_field_list")
    else:
        form = ExpenseFieldForm(instance=field)
    return render(request, "expenses/edit_expense_field.html", {"form": form, "field": field})

@login_required
def delete_expense_field(request, field_id):
    field = get_object_or_404(ExpenseField, id=field_id)
    if request.method == "POST":
        field.delete()
        messages.success(request, "Expense field deleted successfully!")
        return redirect("expense_field_list")
    return render(request, "expenses/delete_expense_field.html", {"field": field})

@login_required
def expense_form(request):
    if request.method == "POST":
        form = ExpenseRecordForm(request.POST)
        if form.is_valid():
            expense_record = form.save(commit=False)
            expense_record.save()
            messages.success(request, "Expense recorded successfully!")
            return redirect("expense_list")
    else:
        form = ExpenseRecordForm()
    return render(request, "expenses/expense_form.html", {"form": form})

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
            return redirect("expense_list")
    else:
        form = ExpenseRecordForm(instance=record)
    return render(request, "expenses/edit_expense_record.html", {"form": form, "record": record})

@login_required
def delete_expense_record(request, record_id):
    record = get_object_or_404(ExpenseRecord, id=record_id)
    if request.method == "POST":
        record.delete()
        messages.success(request, "Expense record deleted successfully!")
        return redirect("expense_list")
    return render(request, "expenses/delete_expense_record.html", {"record": record})