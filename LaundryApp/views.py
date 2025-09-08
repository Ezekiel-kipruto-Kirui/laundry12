from django.shortcuts import render,redirect
from django.http import HttpResponse
from django_daraja.mpesa.core import MpesaClient
import json

from django.http import JsonResponse
# laundry/LaundryApp/views.py
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test

from django.core.paginator import Paginator
from .models import Order, OrderItem, Customer


# views.py

from django.db.models import Prefetch, Q, Sum
from .models import Order, OrderItem





# laundry/LaundryApp/views.py
import json
import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, update_session_auth_hash
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET
from django.db.models import Q, Sum, Count, Prefetch
from django.core.paginator import Paginator
from django.utils import timezone
from django.conf import settings
from django.urls import reverse
from datetime import datetime, timedelta
import csv

from .models import User, UserProfile, Customer, Order, OrderItem, Payment
from .forms import (
    UserRegistrationForm, UserEditForm, ProfileEditForm, 
    CustomerForm, OrderForm, OrderItemForm
)

logger = logging.getLogger(__name__)

# Utility functions
def is_admin(user):
    """Check if user is admin/superuser"""
    return user.is_superuser or user.is_staff

def is_shop_user(user):
    """Check if user belongs to a shop group"""
    return user.groups.filter(name__in=['Shop A', 'Shop B']).exists() or is_admin(user)

# Admin dashboard and user management views
@login_required
@user_passes_test(is_admin)
def admin_dashboard(request):
    """Admin dashboard view with statistics and overview"""
    # Calculate statistics
    total_users = User.objects.count()
    total_customers = Customer.objects.count()
    total_orders = Order.objects.count()
    
    # Recent orders
    recent_orders = Order.objects.select_related('customer').prefetch_related('items') \
        .order_by('-created_at')[:10]
    
    # Shop performance
    shop_performance = {}
    shops = Order.objects.values_list('shop', flat=True).distinct()
    for shop in shops:
        if shop:  # Ensure shop is not empty
            shop_orders = Order.objects.filter(shop=shop)
            shop_performance[shop] = {
                'total_orders': shop_orders.count(),
                'completed_orders': shop_orders.filter(order_status='Completed').count(),
                'pending_orders': shop_orders.filter(order_status='Pending').count(),
                'total_revenue': shop_orders.aggregate(
                    total=Sum('total_price')
                )['total'] or 0
            }
    
    context = {
        'total_users': total_users,
        'total_customers': total_customers,
        'total_orders': total_orders,
        'recent_orders': recent_orders,
        'shop_performance': shop_performance,
    }
    
    return render(request, 'admin/dashboard.html', context)

@login_required
@user_passes_test(is_admin)
def user_management(request):
    """User management view for admin"""
    users = User.objects.all().select_related('profile').prefetch_related('groups')
    
    # Filter by search query
    search_query = request.GET.get('search', '')
    if search_query:
        users = users.filter(
            Q(username__icontains=search_query) |
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(email__icontains=search_query)
        )
    
    # Filter by role
    role_filter = request.GET.get('role', '')
    if role_filter == 'admin':
        users = users.filter(is_superuser=True)
    elif role_filter == 'staff':
        users = users.filter(is_staff=True)
    elif role_filter == 'shop_a':
        users = users.filter(groups__name='Shop A')
    elif role_filter == 'shop_b':
        users = users.filter(groups__name='Shop B')
    
    paginator = Paginator(users, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'users': page_obj,
        'search_query': search_query,
        'role_filter': role_filter,
    }
    
    return render(request, 'admin/user_management.html', context)

@login_required
@user_passes_test(is_admin)
def create_user(request):
    """Create a new user with shop assignment"""
    if request.method == 'POST':
        user_form = UserRegistrationForm(request.POST)
        profile_form = ProfileEditForm(request.POST)
        
        if user_form.is_valid() and profile_form.is_valid():
            user = user_form.save(commit=False)
            user.set_password(user_form.cleaned_data['password'])
            user.save()
            
            # Create or update profile
            profile, created = UserProfile.objects.get_or_create(user=user)
            profile.shop = profile_form.cleaned_data['shop']
            profile.save()
            
            # Assign groups based on shop
            from django.contrib.auth.models import Group
            if profile.shop == 'Shop A':
                group = Group.objects.get(name='Shop A')
                user.groups.add(group)
            elif profile.shop == 'Shop B':
                group = Group.objects.get(name='Shop B')
                user.groups.add(group)
            
            messages.success(request, f'User {user.username} created successfully!')
            return redirect('user_management')
    else:
        user_form = UserRegistrationForm()
        profile_form = ProfileEditForm()
    
    context = {
        'user_form': user_form,
        'profile_form': profile_form,
    }
    
    return render(request, 'admin/create_user.html', context)

@login_required
@user_passes_test(is_admin)
def edit_user(request, user_id):
    """Edit an existing user"""
    user = get_object_or_404(User, id=user_id)
    profile, created = UserProfile.objects.get_or_create(user=user)
    
    if request.method == 'POST':
        user_form = UserEditForm(request.POST, instance=user)
        profile_form = ProfileEditForm(request.POST, instance=profile)
        
        if user_form.is_valid() and profile_form.is_valid():
            user = user_form.save()
            
            # Update profile
            profile.shop = profile_form.cleaned_data['shop']
            profile.save()
            
            # Update groups based on shop
            user.groups.clear()
            from django.contrib.auth.models import Group
            if profile.shop == 'Shop A':
                group = Group.objects.get(name='Shop A')
                user.groups.add(group)
            elif profile.shop == 'Shop B':
                group = Group.objects.get(name='Shop B')
                user.groups.add(group)
            
            messages.success(request, f'User {user.username} updated successfully!')
            return redirect('user_management')
    else:
        user_form = UserEditForm(instance=user)
        profile_form = ProfileEditForm(instance=profile)
    
    context = {
        'user_form': user_form,
        'profile_form': profile_form,
        'user': user,
    }
    
    return render(request, 'admin/edit_user.html', context)

@login_required
@user_passes_test(is_admin)
def delete_user(request, user_id):
    """Delete a user"""
    user = get_object_or_404(User, id=user_id)
    
    if request.method == 'POST':
        username = user.username
        user.delete()
        messages.success(request, f'User {username} deleted successfully!')
        return redirect('user_management')
    
    return render(request, 'admin/confirm_delete.html', {
        'object': user,
        'object_type': 'user',
    })

# Order management views
@login_required
@user_passes_test(is_shop_user)
def order_management(request):
    """Order management view with filtering and search"""
    # Get user's shop
    user_shop = None
    if hasattr(request.user, 'profile'):
        user_shop = request.user.profile.shop
    
    # Base queryset
    if request.user.is_superuser:
        orders = Order.objects.all()
    elif user_shop and user_shop != 'None':
        orders = Order.objects.filter(shop=user_shop)
    else:
        orders = Order.objects.none()
    
    # Apply filters
    status_filter = request.GET.get('status', '')
    if status_filter:
        orders = orders.filter(order_status=status_filter)
    
    payment_filter = request.GET.get('payment', '')
    if payment_filter:
        orders = orders.filter(payment_status=payment_filter)
    
    shop_filter = request.GET.get('shop', '')
    if shop_filter and request.user.is_superuser:
        orders = orders.filter(shop=shop_filter)
    
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    if date_from:
        orders = orders.filter(delivery_date__gte=date_from)
    if date_to:
        orders = orders.filter(delivery_date__lte=date_to)
    
    # Search
    search_query = request.GET.get('search', '')
    if search_query:
        orders = orders.filter(
            Q(uniquecode__icontains=search_query) |
            Q(customer__name__icontains=search_query) |
            Q(customer__phone__icontains=search_query)
        )
    
    # Order by creation date
    orders = orders.select_related('customer').prefetch_related('items').order_by('-created_at')
    
    # Pagination
    paginator = Paginator(orders, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'orders': page_obj,
        'status_filter': status_filter,
        'payment_filter': payment_filter,
        'shop_filter': shop_filter,
        'date_from': date_from,
        'date_to': date_to,
        'search_query': search_query,
        'user_shop': user_shop,
    }
    
    return render(request, 'admin/order_management.html', context)

@login_required
@user_passes_test(is_shop_user)
def create_order(request):
    """Create a new order with multi-step form"""
    # Initialize forms
    customer_form = CustomerForm(request.POST or None)
    order_form = OrderForm(request.POST or None)
    order_item_form = OrderItemForm(request.POST or None)
    
    # Set shop based on user's profile
    if hasattr(request.user, 'profile') and request.user.profile.shop != 'None':
        order_form.fields['shop'].initial = request.user.profile.shop
    
    # Handle AJAX requests
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return handle_ajax_requests(request, customer_form, order_form, order_item_form)
    
    # Handle regular form submission
    if request.method == 'POST':
        return handle_order_submission(request, customer_form, order_form, order_item_form)
    
    # GET request - render empty forms
    context = build_order_context(request, customer_form, order_form, order_item_form)
    return render(request, 'admin/create_order.html', context)

def handle_ajax_requests(request, customer_form, order_form, order_item_form):
    """Handle all AJAX requests for the order form"""
    # Customer existence check
    if 'check_customer' in request.POST:
        return check_customer_existence(request)
    
    # Step submission
    if 'step_submit' in request.POST:
        return handle_step_submission(request, customer_form, order_form, order_item_form)
    
    return JsonResponse({'success': False, 'message': 'Invalid AJAX request'})

def check_customer_existence(request):
    """Check if customer exists by phone number"""
    phone = request.POST.get('phone', '')
    customer = Customer.objects.filter(phone=phone).first()
    
    if customer:
        return JsonResponse({
            'exists': True,
            'name': customer.name,
            'customer': {
                'id': customer.id,
                'name': customer.name,
                'phone': str(customer.phone)
            }
        })
    return JsonResponse({'exists': False})

def handle_step_submission(request, customer_form, order_form, order_item_form):
    """Handle multi-step form submission"""
    current_step = int(request.POST.get('current_step', 1))
    
    # Validate current step
    is_valid, errors = validate_step(current_step, customer_form, order_form, order_item_form, request.POST)
    
    if not is_valid:
        return JsonResponse({
            'success': False,
            'message': 'Please correct the errors',
            'errors': errors
        })
    
    # Process valid step
    try:
        return process_valid_step(current_step, request, customer_form, order_form, order_item_form)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error saving data: {str(e)}'
        })

def validate_step(current_step, customer_form, order_form, order_item_form, post_data):
    """Validate the current step of the form"""
    forms_valid = True
    errors = {}
    
    if current_step == 1:
        customer_form = CustomerForm(post_data)
        if not customer_form.is_valid():
            forms_valid = False
            errors.update(customer_form.errors.get_json_data())
    elif current_step == 2:
        order_form = OrderForm(post_data)
        if not order_form.is_valid():
            forms_valid = False
            errors.update(order_form.errors.get_json_data())
    elif current_step == 3:
        order_item_form = OrderItemForm(post_data)
        if not order_item_form.is_valid():
            forms_valid = False
            errors.update(order_item_form.errors.get_json_data())
    # Step 4 (payment) is optional, no validation needed
    
    return forms_valid, errors

def process_valid_step(current_step, request, customer_form, order_form, order_item_form):
    """Process a valid form step"""
    if current_step == 1:
        return process_customer_step(request, customer_form)
    elif current_step == 2:
        return process_order_step(request, order_form)
    elif current_step == 3:
        return process_order_item_step(request, order_item_form)
    elif current_step == 4:
        return process_payment_step(request)
    
    return JsonResponse({'success': False, 'message': 'Invalid step'})

def process_customer_step(request, customer_form):
    """Process customer information step"""
    phone = request.POST.get('phone', '')
    name = request.POST.get('name', '')
    
    # Check if customer already exists
    existing_customer = Customer.objects.filter(phone=phone).first()
    
    if existing_customer:
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

def process_order_step(request, order_form):
    """Process order information step"""
    if 'customer_id' not in request.session:
        return JsonResponse({
            'success': False,
            'message': 'Customer information is missing. Please start from step 1.'
        })
    
    order = order_form.save(commit=False)
    order.customer_id = request.session['customer_id']
    order.total_price = 0  # Initialize total price
    order.save()
    request.session['order_id'] = order.id
    
    return JsonResponse({
        'success': True,
        'order_id': order.id
    })

def process_order_item_step(request, order_item_form):
    """Process order item step"""
    if 'order_id' not in request.session:
        return JsonResponse({
            'success': False,
            'message': 'Order information is missing. Please start from step 2.'
        })
    
    order_item = order_item_form.save(commit=False)
    order_item.order_id = request.session['order_id']
    order_item.save()
    
    # Update order total price
    order = Order.objects.get(id=request.session['order_id'])
    order.total_price = (order_item.unit_price or 0) * (order_item.quantity or 0)
    order.save()
    
    return JsonResponse({'success': True})

def process_payment_step(request):
    """Process payment information step"""
    if 'order_id' not in request.session:
        return JsonResponse({
            'success': False,
            'message': 'Order information is missing. Please start from step 2.'
        })
    
    # Payment is optional, so only save if data is provided
    payment_method = request.POST.get('payment_method', '')
    
    if payment_method:
        order = Order.objects.get(id=request.session['order_id'])
        payment = Payment(
            order=order,
            price=order.total_price
        )
        payment.save()
    
    # Clear session data
    clear_session_data(request)
    
    return JsonResponse({
        'success': True,
        'redirect_url': reverse('order_success')
    })

def clear_session_data(request):
    """Clear session data used for order creation"""
    session_keys = ['customer_id', 'order_id']
    for key in session_keys:
        if key in request.session:
            del request.session[key]

def handle_order_submission(request, customer_form, order_form, order_item_form):
    """Handle regular form submission (non-AJAX)"""
    if not (customer_form.is_valid() and order_form.is_valid() and 
            order_item_form.is_valid()):
        messages.error(request, 'Please correct the errors below.')
        context = build_order_context(request, customer_form, order_form, order_item_form)
        return render(request, 'admin/create_order.html', context)
    
    try:
        # Enhanced customer handling
        phone = request.POST.get('phone', '')
        existing_customer = Customer.objects.filter(phone=phone).first()
        
        if existing_customer:
            customer = existing_customer
            messages.info(request, f'Using existing customer: {existing_customer.name}')
        else:
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
        
        # Save payment with order reference (if payment data provided)
        payment_method = request.POST.get('payment_method', '')
        if payment_method:
            payment = Payment(
                order=order,
                price=order.total_price
            )
            payment.save()
        
        messages.success(request, f'Order {order.uniquecode} created successfully!')
        return redirect('order_success')
    
    except Exception as e:
        messages.error(request, f'Error saving order: {str(e)}')
        context = build_order_context(request, customer_form, order_form, order_item_form)
        return render(request, 'admin/create_order.html', context)

def build_order_context(request, customer_form, order_form, order_item_form):
    """Build template context for order creation"""
    return {
        'customer_form': customer_form,
        'order_form': order_form,
        'order_item_form': order_item_form,
        'title': 'New Laundry Order',
    }

@login_required
@user_passes_test(is_shop_user)
def order_success(request):
    """Order success page"""
    return render(request, 'admin/order_success.html')

@login_required
@user_passes_test(is_shop_user)
def order_detail(request, order_id):
    """View order details"""
    order = get_object_or_404(Order, id=order_id)
    
    # Check if user has permission to view this order
    if not request.user.is_superuser and hasattr(request.user, 'profile'):
        user_shop = request.user.profile.shop
        if user_shop != 'None' and order.shop != user_shop:
            messages.error(request, 'You do not have permission to view this order.')
            return redirect('order_management')
    
    context = {
        'order': order,
    }
    
    return render(request, 'admin/order_detail.html', context)

@login_required
@user_passes_test(is_shop_user)
def edit_order(request, order_id):
    """Edit an existing order"""
    order = get_object_or_404(Order, id=order_id)
    
    # Check if user has permission to edit this order
    if not request.user.is_superuser and hasattr(request.user, 'profile'):
        user_shop = request.user.profile.shop
        if user_shop != 'None' and order.shop != user_shop:
            messages.error(request, 'You do not have permission to edit this order.')
            return redirect('order_management')
    
    if request.method == 'POST':
        order_form = OrderForm(request.POST, instance=order)
        
        if order_form.is_valid():
            order_form.save()
            messages.success(request, f'Order {order.uniquecode} updated successfully!')
            return redirect('order_detail', order_id=order.id)
    else:
        order_form = OrderForm(instance=order)
    
    context = {
        'order_form': order_form,
        'order': order,
    }
    
    return render(request, 'admin/edit_order.html', context)

@login_required
@user_passes_test(is_shop_user)
def update_order_status(request, order_id):
    """Update order status via AJAX"""
    if request.method == 'POST' and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        order = get_object_or_404(Order, id=order_id)
        
        # Check if user has permission to update this order
        if not request.user.is_superuser and hasattr(request.user, 'profile'):
            user_shop = request.user.profile.shop
            if user_shop != 'None' and order.shop != user_shop:
                return JsonResponse({
                    'success': False,
                    'message': 'You do not have permission to update this order.'
                })
        
        new_status = request.POST.get('status', '')
        
        if new_status in dict(Order.ORDER_STATUS_CHOICES):
            order.order_status = new_status
            order.save()
            
            return JsonResponse({
                'success': True,
                'message': f'Order status updated to {new_status}'
            })
        
        return JsonResponse({
            'success': False,
            'message': 'Invalid status'
        })
    
    return JsonResponse({
        'success': False,
        'message': 'Invalid request'
    })

@login_required
@user_passes_test(is_shop_user)
def export_orders(request):
    """Export orders to CSV"""
    # Get user's shop
    user_shop = None
    if hasattr(request.user, 'profile'):
        user_shop = request.user.profile.shop
    
    # Base queryset
    if request.user.is_superuser:
        orders = Order.objects.all()
    elif user_shop and user_shop != 'None':
        orders = Order.objects.filter(shop=user_shop)
    else:
        orders = Order.objects.none()
    
    # Apply filters from request
    status_filter = request.GET.get('status', '')
    if status_filter:
        orders = orders.filter(order_status=status_filter)
    
    payment_filter = request.GET.get('payment', '')
    if payment_filter:
        orders = orders.filter(payment_status=payment_filter)
    
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    if date_from:
        orders = orders.filter(delivery_date__gte=date_from)
    if date_to:
        orders = orders.filter(delivery_date__lte=date_to)
    
    # Create CSV response
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="orders_export.csv"'
    
    writer = csv.writer(response)
    writer.writerow([
        'Order Code', 'Customer Name', 'Customer Phone', 'Shop', 
        'Order Status', 'Payment Status', 'Delivery Date', 'Total Price'
    ])
    
    for order in orders:
        writer.writerow([
            order.uniquecode,
            order.customer.name,
            order.customer.phone,
            order.shop,
            order.order_status,
            order.payment_status,
            order.delivery_date.strftime('%Y-%m-%d'),
            order.total_price
        ])
    
    return response

# Customer management views
@login_required
@user_passes_test(is_shop_user)
def customer_management(request):
    """Customer management view"""
    customers = Customer.objects.annotate(
        order_count=Count('orders'),
        last_order_date=Max('orders__delivery_date'),
        total_spent=Sum('orders__total_price')
    )
    
    # Filter by search query
    search_query = request.GET.get('search', '')
    if search_query:
        customers = customers.filter(
            Q(name__icontains=search_query) |
            Q(phone__icontains=search_query)
        )
    
    # Filter by shop if user is not superuser
    if not request.user.is_superuser and hasattr(request.user, 'profile'):
        user_shop = request.user.profile.shop
        if user_shop != 'None':
            customers = customers.filter(orders__shop=user_shop).distinct()
    
    paginator = Paginator(customers, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'customers': page_obj,
        'search_query': search_query,
    }
    
    return render(request, 'admin/customer_management.html', context)

@login_required
@user_passes_test(is_shop_user)
def customer_detail(request, customer_id):
    """View customer details and order history"""
    customer = get_object_or_404(Customer, id=customer_id)
    
    # Get customer orders
    orders = customer.orders.all().select_related('customer').prefetch_related('items')
    
    # Filter by shop if user is not superuser
    if not request.user.is_superuser and hasattr(request.user, 'profile'):
        user_shop = request.user.profile.shop
        if user_shop != 'None':
            orders = orders.filter(shop=user_shop)
    
    context = {
        'customer': customer,
        'orders': orders,
    }
    
    return render(request, 'admin/customer_detail.html', context)

# Profile views
@login_required
def profile(request):
    """User profile view"""
    user = request.user
    profile, created = UserProfile.objects.get_or_create(user=user)
    
    if request.method == 'POST':
        user_form = UserEditForm(request.POST, instance=user)
        profile_form = ProfileEditForm(request.POST, instance=profile)
        
        if user_form.is_valid() and profile_form.is_valid():
            user_form.save()
            profile_form.save()
            messages.success(request, 'Profile updated successfully!')
            return redirect('profile')
    else:
        user_form = UserEditForm(instance=user)
        profile_form = ProfileEditForm(instance=profile)
    
    context = {
        'user_form': user_form,
        'profile_form': profile_form,
    }
    
    return render(request, 'admin/profile.html', context)

@login_required
def change_password(request):
    """Change password view"""
    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            messages.success(request, 'Your password was successfully updated!')
            return redirect('profile')
        else:
            messages.error(request, 'Please correct the error below.')
    else:
        form = PasswordChangeForm(request.user)
    
    return render(request, 'admin/change_password.html', {
        'form': form
    })

# API endpoints
@csrf_exempt
@require_POST
@login_required
@user_passes_test(is_shop_user)
def create_order_api(request):
    """API endpoint to create a new order"""
    try:
        data = json.loads(request.body)
        
        # Extract data from request
        customer_data = data.get('customer', {})
        order_data = data.get('order', {})
        items_data = data.get('items', [])
        
        # Create the order
        from .utils import create_laundry_order
        order = create_laundry_order(
            customer_name=customer_data.get('name'),
            customer_phone=customer_data.get('phone'),
            shop=order_data.get('shop'),
            delivery_date=order_data.get('delivery_date'),
            order_items=items_data,
            payment_type=order_data.get('payment_type', 'pending_payment'),
            payment_status=order_data.get('payment_status', 'pending'),
            order_status=order_data.get('order_status', 'pending'),
            address=order_data.get('address', ''),
            addressdetails=order_data.get('addressdetails', ''),
            created_by=request.user
        )
        
        return JsonResponse({
            'success': True,
            'order_code': order.uniquecode,
            'total_price': float(order.total_price),
            'message': 'Order created successfully'
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error creating order: {str(e)}'
        }, status=400)

@require_GET
@login_required
@user_passes_test(is_shop_user)
def order_stats_api(request):
    """API endpoint to get order statistics"""
    # Get user's shop
    user_shop = None
    if hasattr(request.user, 'profile'):
        user_shop = request.user.profile.shop
    
    # Base queryset
    if request.user.is_superuser:
        orders = Order.objects.all()
    elif user_shop and user_shop != 'None':
        orders = Order.objects.filter(shop=user_shop)
    else:
        orders = Order.objects.none()
    
    # Calculate stats
    total_orders = orders.count()
    pending_orders = orders.filter(order_status='pending').count()
    completed_orders = orders.filter(order_status='Completed').count()
    total_revenue = orders.aggregate(total=Sum('total_price'))['total'] or 0
    
    # Recent orders
    recent_orders = orders.select_related('customer').order_by('-created_at')[:5]
    recent_orders_data = [
        {
            'code': order.uniquecode,
            'customer': order.customer.name,
            'status': order.order_status,
            'total': float(order.total_price)
        }
        for order in recent_orders
    ]
    
    return JsonResponse({
        'total_orders': total_orders,
        'pending_orders': pending_orders,
        'completed_orders': completed_orders,
        'total_revenue': float(total_revenue),
        'recent_orders': recent_orders_data
    })





def get_user_shop(user):
    """
    Determine which shop a user has access to.
    You can customize this based on your user model structure.
    """
    if user.is_superuser:
        return None  # Admin can see all shops
    
    # Example: Check user groups or profile for shop assignment
    # Replace this with your actual user permission logic
    if user.groups.filter(name='Shop A Staff').exists():
        return 'Shop A'
    elif user.groups.filter(name='Shop B Staff').exists():
        return 'Shop B'
    
    # Fallback: check username or other fields
    username = user.username.lower()
    if 'shopa' in username:
        return 'Shop A'
    elif 'shopb' in username:
        return 'Shop B'
    
    return None  # No specific shop access

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

def stk_push_callback(request):
    """Handle M-Pesa STK Push callback"""
    return JsonResponse({'ResultCode': 1, 'ResultDesc': 'Invalid request method'})