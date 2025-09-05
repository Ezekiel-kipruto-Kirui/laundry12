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

def customordertable(request):
    # Start with base queryset
    orders = Order.objects.select_related('customer').prefetch_related(
        Prefetch('items', queryset=OrderItem.objects.only('servicetype', 'itemname', 'quantity'))
    ).only(
        'uniquecode', 'order_status', 'payment_status', 'payment_type',
        'shop', 'delivery_date', 'total_price', 'created_at', 'customer__name', 'customer__phone'
    )
    
    # Apply shop filtering based on user role
    if not request.user.is_superuser:
        # For non-superusers, filter by their assigned shop
        if hasattr(request.user, 'profile'):
            user_shop = request.user.profile.shop
            if user_shop != 'None':
                orders = orders.filter(shop=user_shop)
            else:
                # If user has no shop assigned, show no orders
                orders = orders.none()
        else:
            # If user has no profile, show no orders
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
            Q(customer__phone__icontains=search_query)
        )
    
    # Order by creation date
    orders = orders.order_by('-created_at')
    
    # Get counts for stats cards
    total_orders = orders.count()
    pending_orders = orders.filter(order_status='pending').count()
    processing_orders = orders.filter(order_status='processing').count()
    completed_orders = orders.filter(order_status='completed').count()
    
    # Calculate total revenue
    total_revenue = orders.aggregate(total=Sum('total_price'))['total'] or 0
    avg_order_value = total_revenue / total_orders if total_orders > 0 else 0
    
    context = {
        'orders': orders,
        'total_orders': total_orders,
        'pending_orders': pending_orders,
        'processing_orders': processing_orders,
        'completed_orders': completed_orders,
        'total_revenue': total_revenue,
        'avg_order_value': avg_order_value,
        'current_status_filter': status_filter,
        'current_payment_filter': payment_filter,
        'search_query': search_query,
    }
    return render(request, 'orders_table.html', context)

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