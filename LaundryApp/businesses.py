import json
from datetime import datetime, timedelta
from django.db.models import Sum, Count, Q, F
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from HotelApp.models import HotelOrder, HotelExpenseRecord, FoodItem
from LaundryApp.models import Order as LaundryOrder, ExpenseRecord, OrderItem, Customer

def dashboard_home(request):
    return render(request, 'dashboard.html')

@csrf_exempt
@require_http_methods(["GET", "POST"])
def get_dashboard_data(request):
    # Get date filters
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    time_range = request.GET.get('time_range', 'month')
    
    # Set default dates if not provided
    if not start_date or not end_date:
        if time_range == 'all':
            # Get data from the beginning
            start_date = LaundryOrder.objects.earliest('created_at').created_at.date() if LaundryOrder.objects.exists() else timezone.now().date()
            end_date = timezone.now().date()
        else:
            end_date = timezone.now().date()
            start_date = end_date - timedelta(days=30)  # Default to last 30 days
    
    # Convert to datetime objects
    start_dt = timezone.make_aware(datetime.strptime(start_date, '%Y-%m-%d'))
    end_dt = timezone.make_aware(datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1))
    
    # LAUNDRY DATA
    laundry_orders = LaundryOrder.objects.filter(created_at__range=[start_dt, end_dt])
    laundry_expenses = ExpenseRecord.objects.filter(date__range=[start_date, end_date])
    
    # Shop-wise laundry data
    shop_a_orders = laundry_orders.filter(shop='Shop A')
    shop_b_orders = laundry_orders.filter(shop='Shop B')
    
    # Laundry totals
    laundry_total_revenue = laundry_orders.aggregate(total=Sum('total_price'))['total'] or 0
    laundry_total_expenses = laundry_expenses.aggregate(total=Sum('amount'))['total'] or 0
    laundry_total_orders = laundry_orders.count()
    laundry_pending_orders = laundry_orders.filter(order_status='pending').count()
    laundry_completed_orders = laundry_orders.filter(order_status='Completed').count()
    laundry_total_balance = laundry_orders.aggregate(total=Sum('balance'))['total'] or 0
    
    # Shop A specific data
    shop_a_revenue = shop_a_orders.aggregate(total=Sum('total_price'))['total'] or 0
    shop_a_expenses = laundry_expenses.filter(shop='Shop A').aggregate(total=Sum('amount'))['total'] or 0
    shop_a_orders_count = shop_a_orders.count()
    shop_a_balance = shop_a_orders.aggregate(total=Sum('balance'))['total'] or 0
    
    # Shop B specific data
    shop_b_revenue = shop_b_orders.aggregate(total=Sum('total_price'))['total'] or 0
    shop_b_expenses = laundry_expenses.filter(shop='Shop B').aggregate(total=Sum('amount'))['total'] or 0
    shop_b_orders_count = shop_b_orders.count()
    shop_b_balance = shop_b_orders.aggregate(total=Sum('balance'))['total'] or 0
    
    # Common services and items
    common_services = OrderItem.objects.filter(
        order__created_at__range=[start_dt, end_dt]
    ).values('servicetype').annotate(
        count=Count('id')
    ).order_by('-count')[:5]
    
    common_items = OrderItem.objects.filter(
        order__created_at__range=[start_dt, end_dt]
    ).values('itemtype').annotate(
        count=Count('id')
    ).order_by('-count')[:5]
    
    # Top customers
    top_customers = Customer.objects.filter(
        orders__created_at__range=[start_dt, end_dt]
    ).annotate(
        order_count=Count('orders'),
        total_spent=Sum('orders__total_price')
    ).order_by('-total_spent')[:10]
    
    # HOTEL DATA
    hotel_orders = HotelOrder.objects.filter(created_at__range=[start_dt, end_dt])
    hotel_expenses = HotelExpenseRecord.objects.filter(date__range=[start_date, end_date])
    
    hotel_total_revenue = hotel_orders.aggregate(total=Sum(F('order_items__quantity') * F('order_items__food_item__price')))['total'] or 0
    hotel_total_expenses = hotel_expenses.aggregate(total=Sum('amount'))['total'] or 0
    hotel_total_orders = hotel_orders.count()
    hotel_pending_orders = hotel_orders.filter(order_status='In Progress').count()
    hotel_completed_orders = hotel_orders.filter(order_status='Served').count()
    
    # Monthly growth data
    months_data = []
    current_date = start_dt
    while current_date <= end_dt:
        month_start = current_date.replace(day=1)
        next_month = month_start + timedelta(days=32)
        month_end = next_month.replace(day=1) - timedelta(days=1)
        
        if month_end > end_dt:
            month_end = end_dt
        
        month_laundry_revenue = LaundryOrder.objects.filter(
            created_at__range=[month_start, month_end]
        ).aggregate(total=Sum('total_price'))['total'] or 0
        
        month_hotel_revenue = HotelOrder.objects.filter(
            created_at__range=[month_start, month_end]
        ).aggregate(total=Sum(F('order_items__quantity') * F('order_items__food_item__price')))['total'] or 0
        
        months_data.append({
            'month': month_start.strftime('%b %Y'),
            'laundry': float(month_laundry_revenue),
            'hotel': float(month_hotel_revenue)
        })
        
        current_date = next_month
    
    # Prepare response data
    data = {
        'laundry': {
            'total_revenue': float(laundry_total_revenue),
            'total_expenses': float(laundry_total_expenses),
            'total_orders': laundry_total_orders,
            'pending_orders': laundry_pending_orders,
            'completed_orders': laundry_completed_orders,
            'total_balance': float(laundry_total_balance),
            'shop_a': {
                'revenue': float(shop_a_revenue),
                'expenses': float(shop_a_expenses),
                'orders': shop_a_orders_count,
                'balance': float(shop_a_balance)
            },
            'shop_b': {
                'revenue': float(shop_b_revenue),
                'expenses': float(shop_b_expenses),
                'orders': shop_b_orders_count,
                'balance': float(shop_b_balance)
            },
            'common_services': list(common_services),
            'common_items': list(common_items),
            'top_customers': [
                {
                    'name': customer.name,
                    'phone': str(customer.phone),
                    'order_count': customer.order_count,
                    'total_spent': float(customer.total_spent or 0)
                }
                for customer in top_customers
            ]
        },
        'hotel': {
            'total_revenue': float(hotel_total_revenue),
            'total_expenses': float(hotel_total_expenses),
            'total_orders': hotel_total_orders,
            'pending_orders': hotel_pending_orders,
            'completed_orders': hotel_completed_orders
        },
        'comparison': {
            'months': months_data,
            'doughnut_data': {
                'laundry_revenue': float(laundry_total_revenue),
                'hotel_revenue': float(hotel_total_revenue),
                'laundry_expenses': float(laundry_total_expenses),
                'hotel_expenses': float(hotel_total_expenses)
            }
        },
        'date_range': {
            'start_date': start_date,
            'end_date': end_date
        }
    }
    
    return JsonResponse(data)