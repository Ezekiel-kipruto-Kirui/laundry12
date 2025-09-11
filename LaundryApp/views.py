from django.shortcuts import render, redirect
from django.http import HttpResponse, JsonResponse
from django_daraja.mpesa.core import MpesaClient
import json
import logging
from functools import wraps
from datetime import datetime

# Django imports
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import Http404
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_http_methods
from django.db.models import Q, Prefetch, Sum, Count
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.contrib.auth import login
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.models import User

# Local imports
from .models import Customer, Order, OrderItem, Payment,UserProfile
from .forms import CustomerForm, OrderForm, OrderItemForm,UserEditForm, UserCreateForm
from .resource import OrderResource
from .analytics import DashboardAnalytics

# Setup logger
logger = logging.getLogger(__name__)

# Constants
SHOP_A = 'Shop A'
SHOP_B = 'Shop B'


def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self.analytics = DashboardAnalytics(self)

def get_queryset(request):
    return super().get_queryset(request).annotate(
        items_count=Count('items')
    )

def filter_by_shops(queryset, shops):
    return queryset.filter(shop__in=shops)

def object_belongs_to_user_shops(self, obj, user_shops):
    return obj.shop in user_shops

    
def get_user_shops(request):
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

def is_superuser(user):
    return user.is_superuser

# Views
@login_required
def dashboard_view(request):
    if not request.user.is_superuser:
        logger.warning(f"Non-superuser {request.user.username} attempted to access dashboard")
        raise Http404("You do not have permission to access this dashboard.")

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
def customordertable(request):
    # Start with base queryset - exclude delivered orders from the main query
    orders = Order.objects.select_related('customer').prefetch_related(
        Prefetch('items', queryset=OrderItem.objects.only(
            'servicetype', 'itemname', 'quantity', 'itemtype', 
            'itemcondition', 'total_item_price',
        ))
    ).only(
        'uniquecode', 'order_status', 'payment_status','payment_type',
        'shop', 'delivery_date', 'amount_paid', 'balance', 'total_price', 'created_at', 
        'customer__name', 'customer__phone', 'address', 'addressdetails'
    ).exclude(order_status='delivered')  # Exclude delivered orders

    # Apply shop filtering based on user group
    user_shops = get_user_shops(request)
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
    paginator = Paginator(orders, 15)  # Show 25 orders per page
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

@csrf_exempt
@require_POST
@login_required
def create_order_api(request):
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

@login_required
def createorder(request):
    """View to handle order creation with Django forms"""
    # Get user's shop based on group membership
    user_shops = get_user_shops(request)
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
        OrderItemFormSet = forms.formset_factory(OrderItemForm, extra=0)
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
                return redirect('customordertable')  # Update this to your URL name
                
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
def check_customer(request):
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

@login_required
def generaldashboard(request):
    if not request.user.is_authenticated:
        return redirect('login')  # Update to your login URL name

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
    return redirect('login')  # Replace 'login' with your login URL name
@login_required
@user_passes_test(is_superuser)
def user_management(request):
    """User management page for superusers"""
    users = User.objects.select_related('profile').all().order_by('-date_joined')
    
    # Get filter parameters
    search_query = request.GET.get('search', '')
    shop_filter = request.GET.get('shop', '')
    status_filter = request.GET.get('status', '')
    
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
        {'value': 'staff', 'label': 'Staff', 'selected': status_filter == 'staff'}
    ]
    
    # Pagination
    paginator = Paginator(users, 20)
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
    
    pagination_url_suffix = '&'.join(pagination_params)
    if pagination_url_suffix:
        pagination_url_suffix = '&' + pagination_url_suffix
    
    context = {
        'users': page_obj,
        'search_query': search_query,
        'shop_options': shop_options,
        'status_options': status_options,
        'total_users': users.count(),
        'active_users': users.filter(is_active=True).count(),
        'staff_users': users.filter(is_staff=True).count(),
        'pagination_url_suffix': pagination_url_suffix,
    }
    
    return render(request, 'Admin/user_management.html', context)
@login_required
@user_passes_test(is_superuser)
def user_add(request):
    """Add new user"""
    if request.method == 'POST':
        form = UserCreateForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(request, f'User {user.username} created successfully!')
            return redirect('user_management')
    else:
        form = UserCreateForm()
    
    context = {
        'form': form,
        'title': 'Add New User'
    }
    
    return render(request, 'Admin/user_form.html', context)

@login_required
@user_passes_test(is_superuser)
def user_edit(request, pk):
    """Edit user information"""
    user = get_object_or_404(User, pk=pk)
    
    if request.method == 'POST':
        form = UserEditForm(request.POST, instance=user)
        if form.is_valid():
            user = form.save()
            messages.success(request, f'User {user.username} updated successfully!')
            return redirect('user_management')
    else:
        form = UserEditForm(instance=user)
    
    context = {
        'form': form,
        'user': user,
        'title': f'Edit User - {user.username}'
    }
    
    return render(request, 'Admin/user_form.html', context)

@login_required
@user_passes_test(is_superuser)
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
@user_passes_test(is_superuser)
def user_profile(request, pk):
    """View user profile and details"""
    user = get_object_or_404(User, pk=pk)
    profile = getattr(user, 'profile', None)
    
    # Get user's order statistics if they created any orders
    user_orders = Order.objects.filter(created_by=user)
    total_orders = user_orders.count()
    total_revenue = user_orders.aggregate(total=Sum('total_price'))['total'] or 0
    
    context = {
        'user': user,
        'profile': profile,
        'total_orders': total_orders,
        'total_revenue': total_revenue,
    }
    
    return render(request, 'Admin/user_profile.html', context)

@login_required
def customer_management(request):
    """Customer management page with search and filtering"""
    customers = Customer.objects.annotate(
        order_count=Count('orders'),
        total_spent=Sum('orders__total_price')
    ).order_by('-id')  # Fixed: Changed from '-created_at' to '-id'
    
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