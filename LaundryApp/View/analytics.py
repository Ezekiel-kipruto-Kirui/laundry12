import hashlib
import json
import logging
from collections import Counter
from functools import lru_cache

# Django core imports
from django.db import models
from django.db.models import (
    Avg, Count, DecimalField, Q, Sum, Case, When, IntegerField
)
from django.db.models.functions import Coalesce, ExtractMonth, ExtractYear
from django.utils.timezone import now
from django.http import JsonResponse

# Local imports
from ..models import Order, OrderItem, ExpenseRecord
from HotelApp.models import HotelOrder, HotelExpenseRecord, HotelOrderItem

# Setup logger
logger = logging.getLogger(__name__)

# --- Constants ---
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
ACTIVE_ORDER_STATUSES = ['pending', 'Completed', 'Delivered_picked']
# Hotel orders don't have status anymore, so we'll use all hotel orders
HOTEL_ACTIVE_STATUSES = []  # Empty since no status field

# Payment status constants
PAYMENT_STATUS_PENDING = 'pending'
PAYMENT_STATUS_PARTIAL = 'partial'
PAYMENT_STATUS_COMPLETE = 'complete'
PAYMENT_STATUS_OVERDUE = 'overdue'

# Payment type constants
PAYMENT_TYPES = ['cash', 'mpesa', 'card', 'bank_transfer', 'other','None']


class DashboardAnalytics:
    """
    Handles all analytics and dashboard-related functionality for the laundry management system.
    """
    
    def __init__(self, admin_instance):
        self.admin_instance = admin_instance
    
    def get_user_shops(self, request):
        return self.admin_instance.get_user_shops(request)
    
    def _get_empty_dashboard_data(self):
        return {
            'order_stats': {
                'total_orders': 0, 'pending_orders': 0, 'completed_orders': 0,
                'delivered_orders': 0, 'total_revenue': 0, 'avg_order_value': 0,
                'total_balance': 0, 'total_amount_paid': 0
            },
            'payment_stats': {
                'pending_payments': 0,
                'partial_payments': 0,
                'complete_payments': 0,
                'overdue_payments': 0,
                'total_pending_amount': 0,
                'total_partial_amount': 0,
                'total_complete_amount': 0,
                'total_collected_amount': 0,
                'total_balance_amount': 0
            },
            'payment_type_stats': {
                'cash': {'count': 0, 'total_amount': 0, 'amount_collected': 0},
                'mpesa': {'count': 0, 'total_amount': 0, 'amount_collected': 0},
                'card': {'count': 0, 'total_amount': 0, 'amount_collected': 0},
                'bank_transfer': {'count': 0, 'total_amount': 0, 'amount_collected': 0},
                'other': {'count': 0, 'total_amount': 0, 'amount_collected': 0}
            },
            'expense_stats': {
                'total_expenses': 0,
                'shop_a_expenses': 0,
                'shop_b_expenses': 0,
                'average_expense': 0
            },
            'hotel_stats': {
                'total_orders': 0,
                'total_revenue': 0,
                'avg_order_value': 0,
                'total_expenses': 0,
                'net_profit': 0
            },
            'business_growth': {
                'total_revenue': 0,
                'total_orders': 0,
                'total_expenses': 0,
                'net_profit': 0
            },
            'revenue_by_shop': [],
            'balance_by_shop': [],
            'expenses_by_shop': [],
            'common_customers': [],
            'payment_methods': [],
            'top_services': [],
            'common_items': [],
            'service_types': [],
            'line_chart_data': [],
            'monthly_order_volume': [],
            'monthly_expenses_data': [],
            'monthly_business_growth': [],
            'shop_a_stats': {
                'revenue': 0, 'total_orders': 0, 'pending_orders': 0, 'completed_orders': 0,
                'pending_payments': 0, 'partial_payments': 0, 'complete_payments': 0,
                'total_balance': 0, 'total_amount_paid': 0, 'total_expenses': 0,
                'net_profit': 0
            },
            'shop_b_stats': {
                'revenue': 0, 'total_orders': 0, 'pending_orders': 0, 'completed_orders': 0,
                'pending_payments': 0, 'partial_payments': 0, 'complete_payments': 0,
                'total_balance': 0, 'total_amount_paid': 0, 'total_expenses': 0,
                'net_profit': 0
            },
            'orders_by_payment_status': {
                'pending': [],
                'partial': [],
                'complete': [],
                'overdue': []
            }
        }
    
    def _calculate_payment_type_stats(self, base_queryset):
        """
        Calculate payment statistics by payment type including amount collected.
        """
        payment_type_stats = {}
        
        for payment_type in PAYMENT_TYPES:
            # Get orders with this payment type
            payment_orders = base_queryset.filter(payment_type=payment_type)
            
            stats = payment_orders.aggregate(
                count=Count('id'),
                total_amount=Coalesce(Sum('total_price'), 0, output_field=DecimalField()),
                amount_collected=Coalesce(Sum('amount_paid'), 0, output_field=DecimalField())
            )
            
            payment_type_stats[payment_type] = {
                'count': stats['count'],
                'total_amount': stats['total_amount'],
                'amount_collected': stats['amount_collected']
            }
        
        return payment_type_stats
    
    def _calculate_hotel_stats(self, request, selected_year=None, selected_month=None, from_date=None, to_date=None):
        """
        Calculate hotel statistics including orders, revenue, and expenses.
        """
        # Hotel orders don't have status field anymore, so get all
        hotel_orders = HotelOrder.objects.all()
        
        # Apply date filters
        if selected_year:
            hotel_orders = hotel_orders.filter(created_at__year=selected_year)
        if selected_month:
            hotel_orders = hotel_orders.filter(created_at__month=selected_month)
        if from_date and to_date:
            hotel_orders = hotel_orders.filter(created_at__date__range=[from_date, to_date])
        
        # Calculate hotel order statistics - use price from HotelOrderItem
        hotel_stats = hotel_orders.aggregate(
            total_orders=Count('id'),
            total_revenue=Coalesce(Sum(
                Case(
                    When(order_items__isnull=False, 
                         then=models.F('order_items__quantity') * models.F('order_items__price')),
                    default=0,
                    output_field=DecimalField()
                )
            ), 0, output_field=DecimalField())
        )
        
        # Calculate average order value
        if hotel_stats['total_orders'] > 0:
            hotel_stats['avg_order_value'] = hotel_stats['total_revenue'] / hotel_stats['total_orders']
        else:
            hotel_stats['avg_order_value'] = 0
        
        # Calculate hotel expenses
        hotel_expenses = HotelExpenseRecord.objects.all()
        
        if selected_year:
            hotel_expenses = hotel_expenses.filter(date__year=selected_year)
        if selected_month:
            hotel_expenses = hotel_expenses.filter(date__month=selected_month)
        if from_date and to_date:
            hotel_expenses = hotel_expenses.filter(date__range=[from_date, to_date])
        
        total_hotel_expenses = hotel_expenses.aggregate(
            total_expenses=Coalesce(Sum('amount'), 0, output_field=DecimalField())
        )['total_expenses']
        
        hotel_stats['total_expenses'] = total_hotel_expenses
        hotel_stats['net_profit'] = hotel_stats['total_revenue'] - total_hotel_expenses
        
        return hotel_stats
    
    def _calculate_laundry_revenue(self, base_queryset):
        """
        Calculate laundry revenue by summing up all order items properly.
        """
        # Get all order IDs from the base queryset
        order_ids = base_queryset.values_list('id', flat=True)
        
        # Calculate total revenue from order items
        revenue_stats = OrderItem.objects.filter(order_id__in=order_ids).aggregate(
            total_revenue=Coalesce(Sum('total_item_price'), 0, output_field=DecimalField())
        )
        #print(revenue_stats)
        return revenue_stats['total_revenue']
    
    def _calculate_order_stats(self, base_queryset):
        """
        Calculate order statistics including balance information.
        """
        # First get basic order stats
        order_stats = base_queryset.aggregate(
            total_orders=Count('id'),
            pending_orders=Count('id', filter=Q(order_status='pending')),
            completed_orders=Count('id', filter=Q(order_status='Completed')),
            delivered_orders=Count('id', filter=Q(order_status='Delivered_picked')),
            total_amount_paid=Coalesce(Sum('amount_paid'), 0, output_field=DecimalField()),
            total_balance=Coalesce(Sum('balance'), 0, output_field=DecimalField()),
            avg_order_value=Coalesce(Avg('total_price'), 0, output_field=DecimalField())
        )
        
        # Calculate total revenue from order items (correct method)
        order_stats['total_revenue'] = self._calculate_laundry_revenue(base_queryset)
        #print(order_stats)
        return order_stats
    
    def _calculate_expense_stats(self, request, selected_year=None, selected_month=None, from_date=None, to_date=None):
        """
        Calculate expense statistics for the dashboard.
        """
        expenses = ExpenseRecord.objects.all()
        
        # Apply date filters
        if selected_year:
            expenses = expenses.filter(date__year=selected_year)
        if selected_month:
            expenses = expenses.filter(date__month=selected_month)
        if from_date and to_date:
            expenses = expenses.filter(date__range=[from_date, to_date])
        
        # Apply shop filtering
        user_shops = self.get_user_shops(request)
        if user_shops is not None:
            if user_shops:
                expenses = expenses.filter(shop__in=user_shops)
            else:
                expenses = ExpenseRecord.objects.none()
        
        # Calculate expense statistics
        expense_stats = expenses.aggregate(
            total_expenses=Coalesce(Sum('amount'), 0, output_field=DecimalField()),
            average_expense=Coalesce(Avg('amount'), 0, output_field=DecimalField()),
            expense_count=Count('id')
        )
        
        # Calculate shop-specific expenses
        shop_a_expenses = expenses.filter(shop='Shop A').aggregate(
            total=Coalesce(Sum('amount'), 0, output_field=DecimalField())
        )['total']
        
        shop_b_expenses = expenses.filter(shop='Shop B').aggregate(
            total=Coalesce(Sum('amount'), 0, output_field=DecimalField())
        )['total']
        
        expense_stats.update({
            'shop_a_expenses': shop_a_expenses,
            'shop_b_expenses': shop_b_expenses
        })
        
        return expense_stats
    
    def _get_expenses_by_shop(self, request, selected_year=None, selected_month=None, from_date=None, to_date=None):
        """
        Get expenses grouped by shop.
        """
        expenses = ExpenseRecord.objects.all()
        
        # Apply date filters
        if selected_year:
            expenses = expenses.filter(date__year=selected_year)
        if selected_month:
            expenses = expenses.filter(date__month=selected_month)
        if from_date and to_date:
            expenses = expenses.filter(date__range=[from_date, to_date])
        
        # Apply shop filtering
        user_shops = self.get_user_shops(request)
        if user_shops is not None:
            if user_shops:
                expenses = expenses.filter(shop__in=user_shops)
            else:
                expenses = ExpenseRecord.objects.none()
        
        expenses_by_shop = list(expenses.values('shop').annotate(
            total_expenses=Sum('amount'),
            expense_count=Count('id')
        ).order_by('-total_expenses'))
        
        return expenses_by_shop
    
    def _get_monthly_expenses_data(self, request, selected_year=None):
        """
        Get monthly expenses data for charts.
        """
        monthly_expenses_data = []
        
        if not selected_year:
            selected_year = now().year
        
        user_shops = self.get_user_shops(request)
        if user_shops is None:
            shops = ['Shop A', 'Shop B']
        else:
            shops = user_shops
        
        for shop_name in shops:
            monthly_data = ExpenseRecord.objects.filter(
                shop=shop_name,
                date__year=selected_year
            ).annotate(
                month=ExtractMonth('date')
            ).values('month').annotate(
                expenses=Coalesce(Sum('amount'), 0, output_field=DecimalField())
            ).order_by('month')
            
            expenses_by_month = {item['month']: float(item['expenses']) for item in monthly_data}
            monthly_values = [expenses_by_month.get(month, 0) for month in range(1, 13)]
            
            if any(monthly_values):
                color_seed = f"{shop_name}_expenses".encode('utf-8')
                hex_color = hashlib.md5(color_seed).hexdigest()[0:6]
                monthly_expenses_data.append({
                    'label': f'{shop_name} Expenses',
                    'data': monthly_values,
                    'borderColor': f'#{hex_color}',
                    'backgroundColor': f'#{hex_color}50',
                    'fill': True,
                    'months': MONTHS
                })
        
        return monthly_expenses_data

    def _get_monthly_business_growth(self, request, selected_year=None):
        """
        Get monthly business growth data combining laundry and hotel business.
        """
        monthly_business_growth = []
        
        if not selected_year:
            selected_year = now().year
        
        # **FIXED**: Use consistent date fields
        # Get monthly laundry revenue - using delivery_date consistently
        laundry_monthly_data = Order.objects.filter(
            delivery_date__year=selected_year,
            order_status__in=ACTIVE_ORDER_STATUSES
        ).annotate(
            month=ExtractMonth('delivery_date')
        ).values('month').annotate(
            laundry_revenue=Coalesce(Sum(
                Case(
                    When(items__isnull=False, 
                        then=models.F('items__total_item_price')),
                    default=0,
                    output_field=DecimalField()
                )
            ), 0, output_field=DecimalField()),
            laundry_orders=Count('id')
        ).order_by('month')
        
        # Get monthly hotel revenue - using created_at consistently
        hotel_monthly_data = HotelOrder.objects.filter(
            created_at__year=selected_year
        ).annotate(
            month=ExtractMonth('created_at')
        ).values('month').annotate(
            hotel_revenue=Coalesce(Sum(
                Case(
                    When(order_items__isnull=False, 
                        then=models.F('order_items__quantity') * models.F('order_items__price')),
                    default=0,
                    output_field=DecimalField()
                )
            ), 0, output_field=DecimalField()),
            hotel_orders=Count('id')
        ).order_by('month')
        
        # Combine data
        laundry_by_month = {item['month']: {
            'revenue': float(item['laundry_revenue']),
            'orders': item['laundry_orders']
        } for item in laundry_monthly_data}
        
        hotel_by_month = {item['month']: {
            'revenue': float(item['hotel_revenue']),
            'orders': item['hotel_orders']
        } for item in hotel_monthly_data}
        
        # Prepare datasets for chart
        laundry_revenue_data = [laundry_by_month.get(month, {'revenue': 0})['revenue'] for month in range(1, 13)]
        hotel_revenue_data = [hotel_by_month.get(month, {'revenue': 0})['revenue'] for month in range(1, 13)]
        total_revenue_data = [laundry_revenue_data[i] + hotel_revenue_data[i] for i in range(12)]
        
        if any(laundry_revenue_data) or any(hotel_revenue_data):
            monthly_business_growth = [
                {
                    'label': 'Laundry Revenue',
                    'data': laundry_revenue_data,
                    'borderColor': '#36A2EB',
                    'backgroundColor': '#36A2EB50',
                    'fill': False
                },
                {
                    'label': 'Hotel Revenue',
                    'data': hotel_revenue_data,
                    'borderColor': '#FF6384',
                    'backgroundColor': '#FF638450',
                    'fill': False
                },
                {
                    'label': 'Total Revenue',
                    'data': total_revenue_data,
                    'borderColor': '#4BC0C0',
                    'backgroundColor': '#4BC0C050',
                    'fill': False,
                    'borderDash': [5, 5]
                }
            ]
        
        return monthly_business_growth

    def _get_base_queryset(self, request, selected_year, selected_month=None, from_date=None, to_date=None, payment_status=None, shop=None):
        """
        Get the base queryset with proper filtering.
        """
        base_queryset = Order.objects.filter(order_status__in=ACTIVE_ORDER_STATUSES)

        # Apply filters
        if shop:
            base_queryset = base_queryset.filter(shop=shop)
        if selected_year:
            base_queryset = base_queryset.filter(delivery_date__year=selected_year)
        if selected_month:
            base_queryset = base_queryset.filter(delivery_date__month=selected_month)
        if from_date and to_date:
            base_queryset = base_queryset.filter(delivery_date__range=[from_date, to_date])

        # Apply payment status filtering
        if payment_status:
            if payment_status == PAYMENT_STATUS_PENDING:
                base_queryset = base_queryset.filter(
                    Q(amount_paid=0) | Q(amount_paid__isnull=True)
                )
            elif payment_status == PAYMENT_STATUS_PARTIAL:
                base_queryset = base_queryset.filter(
                    Q(amount_paid__gt=0, amount_paid__lt=models.F('total_price')) |
                    Q(balance__gt=0)
                )
            elif payment_status == PAYMENT_STATUS_COMPLETE:
                base_queryset = base_queryset.filter(
                    Q(amount_paid__gte=models.F('total_price')) |
                    Q(balance=0)
                )
            elif payment_status == PAYMENT_STATUS_OVERDUE:
                base_queryset = base_queryset.filter(
                    Q(delivery_date__lt=now().date()) & 
                    (Q(amount_paid__lt=models.F('total_price')) | 
                     Q(balance__gt=0) | 
                     Q(amount_paid__isnull=True))
                )

        # Apply shop filtering for non-superusers
        user_shops = self.get_user_shops(request)
        if user_shops is not None:
            if user_shops:
                base_queryset = base_queryset.filter(shop__in=user_shops)
            else:
                base_queryset = Order.objects.none()

        return base_queryset
    
    def _calculate_payment_stats(self, base_queryset):
        """
        Calculate comprehensive payment statistics including total amounts for each payment status.
        """
        payment_stats = base_queryset.aggregate(
            total_orders=Count('id'),
            
            # Count of orders in each payment status
            pending_payments=Count('id', filter=Q(amount_paid=0) | Q(amount_paid__isnull=True)),
            partial_payments=Count('id', filter=Q(amount_paid__gt=0, amount_paid__lt=models.F('total_price')) | Q(balance__gt=0)),
            complete_payments=Count('id', filter=Q(amount_paid__gte=models.F('total_price')) | Q(balance=0)),
            
            # Total amounts for each payment status
            total_pending_amount=Coalesce(
                Sum(
                    Case(
                        When(Q(amount_paid=0) | Q(amount_paid__isnull=True), then=models.F('total_price')),
                        default=0,
                        output_field=DecimalField()
                    )
                ), 0, output_field=DecimalField()
            ),
            total_partial_amount=Coalesce(
                Sum(
                    Case(
                        When(Q(amount_paid__gt=0) & Q(amount_paid__lt=models.F('total_price')), 
                             then=models.F('amount_paid')),
                        default=0,
                        output_field=DecimalField()
                    )
                ), 0, output_field=DecimalField()
            ),
            total_complete_amount=Coalesce(
                Sum(
                    Case(
                        When(Q(amount_paid__gte=models.F('total_price')) | Q(balance=0), 
                             then=models.F('total_price')),
                        default=0,
                        output_field=DecimalField()
                    )
                ), 0, output_field=DecimalField()
            ),
            
            # Overall payment statistics
            total_collected_amount=Coalesce(Sum('amount_paid'), 0, output_field=DecimalField()),
            total_balance_amount=Coalesce(Sum('balance'), 0, output_field=DecimalField())
        )
        
        # Calculate overdue stats
        overdue_stats = base_queryset.filter(
            delivery_date__lt=now().date()
        ).aggregate(
            overdue_payments=Count('id', filter=Q(amount_paid__lt=models.F('total_price')) | Q(balance__gt=0)),
            total_overdue_amount=Coalesce(
                Sum(
                    Case(
                        When(Q(amount_paid__lt=models.F('total_price')), 
                             then=models.F('total_price') - models.F('amount_paid')),
                        When(Q(balance__gt=0), then=models.F('balance')),
                        default=0,
                        output_field=DecimalField()
                    )
                ), 0, output_field=DecimalField()
            )
        )
        
        payment_stats.update(overdue_stats)
        #print(payment_stats)
        return payment_stats
   
    def _get_orders_by_payment_status(self, base_queryset, shop=None):
        """
        Get actual order objects grouped by payment status.
        """
        if shop:
            base_queryset = base_queryset.filter(shop=shop)
        
        orders_by_payment_status = {
            'pending': list(base_queryset.filter(
                Q(amount_paid=0) | Q(amount_paid__isnull=True)
            ).select_related('customer').order_by('-delivery_date')[:50]),
            
            'partial': list(base_queryset.filter(
                Q(amount_paid__gt=0, amount_paid__lt=models.F('total_price')) |
                Q(balance__gt=0)
            ).select_related('customer').order_by('-delivery_date')[:50]),
            
            'complete': list(base_queryset.filter(
                Q(amount_paid__gte=models.F('total_price')) |
                Q(balance=0)
            ).select_related('customer').order_by('-delivery_date')[:50]),
            
            'overdue': list(base_queryset.filter(
                Q(delivery_date__lt=now().date()) & 
                (Q(amount_paid__lt=models.F('total_price')) | 
                 Q(balance__gt=0) | 
                 Q(amount_paid__isnull=True))
            ).select_related('customer').order_by('-delivery_date')[:50])
        }
        
        return orders_by_payment_status
    
    def _get_shop_specific_orders(self, base_queryset, shop_name, expense_stats):
        """
        Get orders and payment statistics for a specific shop.
        """
        shop_orders = base_queryset.filter(shop=shop_name)
        
        # Calculate payment statistics for the specific shop
        shop_payment_stats = shop_orders.aggregate(
            # Counts
            pending_payments=Count('id', filter=Q(amount_paid=0) | Q(amount_paid__isnull=True)),
            partial_payments=Count('id', filter=Q(amount_paid__gt=0, amount_paid__lt=models.F('total_price')) | Q(balance__gt=0)),
            complete_payments=Count('id', filter=Q(amount_paid__gte=models.F('total_price')) | Q(balance=0)),
            
            # Amounts
            total_pending_amount=Coalesce(
                Sum(
                    Case(
                        When(Q(amount_paid=0) | Q(amount_paid__isnull=True), then=models.F('total_price')),
                        default=0,
                        output_field=DecimalField()
                    )
                ), 0, output_field=DecimalField()
            ),
            total_partial_amount=Coalesce(
                Sum(
                    Case(
                        When(Q(amount_paid__gt=0) & Q(amount_paid__lt=models.F('total_price')), 
                             then=models.F('amount_paid')),
                        default=0,
                        output_field=DecimalField()
                    )
                ), 0, output_field=DecimalField()
            ),
            total_complete_amount=Coalesce(
                Sum(
                    Case(
                        When(Q(amount_paid__gte=models.F('total_price')) | Q(balance=0), 
                             then=models.F('total_price')),
                        default=0,
                        output_field=DecimalField()
                    )
                ), 0, output_field=DecimalField()
            )
        )
        
        shop_stats = shop_orders.aggregate(
            revenue=Coalesce(Sum('total_price'), 0, output_field=DecimalField()),
            total_amount_paid=Coalesce(Sum('amount_paid'), 0, output_field=DecimalField()),
            total_balance=Coalesce(Sum('balance'), 0, output_field=DecimalField()),
            total_orders=Count('id'),
            pending_orders=Count('id', filter=Q(order_status='pending')),
            completed_orders=Count('id', filter=Q(order_status='Completed'))
        )
        
        # Add payment statistics to shop stats
        shop_stats.update(shop_payment_stats)
        
        # Add expense information
        if shop_name == 'Shop A':
            shop_stats['total_expenses'] = expense_stats.get('shop_a_expenses', 0)
        elif shop_name == 'Shop B':
            shop_stats['total_expenses'] = expense_stats.get('shop_b_expenses', 0)
        else:
            shop_stats['total_expenses'] = 0
        
        # Calculate net profit
        shop_stats['net_profit'] = shop_stats['revenue'] - shop_stats['total_expenses']
        
        # Get orders by payment status for this shop
        shop_orders_by_status = self._get_orders_by_payment_status(base_queryset, shop=shop_name)
        
        return {
            'stats': shop_stats,
            'orders_by_payment_status': shop_orders_by_status
        }
    
    def _process_multiselect_services(self, order_ids):
        """
        Process MultiSelectField service data to count individual services.
        """
        order_item_data = OrderItem.objects.filter(order_id__in=order_ids)
        
        # Count individual services from MultiSelectField
        service_counter = Counter()
        
        for item in order_item_data.only('servicetype'):
            if item.servicetype:
                # MultiSelectField returns a list of selected values
                services = item.servicetype
                if services:
                    # Count individual services
                    for service in services:
                        service_counter[service] += 1
        
        # Get top individual services
        top_services = [{'servicetype': service, 'count': count} 
                       for service, count in service_counter.most_common(10)]
        
        return top_services
    
    @lru_cache(maxsize=32)
    def _get_common_items_data(self, order_ids):
        """
        Get common items data with caching.
        """
        order_item_data = OrderItem.objects.filter(order_id__in=order_ids)
        all_items = []
        for item in order_item_data.only('itemname'):
            if item.itemname:
                item_list = [i.strip() for i in item.itemname.split(',') if i.strip()]
                all_items.extend(item_list)
        item_counter = Counter(all_items)
        return [{'itemname': item, 'count': count} for item, count in item_counter.most_common(5)]
    
    def get_dashboard_data(self, request, selected_year, selected_month=None, from_date=None, to_date=None, payment_status=None, shop=None):
        """
        Fetch comprehensive dashboard data with optimized queries.
        """
        try:
            base_queryset = self._get_base_queryset(request, selected_year, selected_month, from_date, to_date, payment_status, shop)
            
            # Calculate statistics
            expense_stats = self._calculate_expense_stats(request, selected_year, selected_month, from_date, to_date)
            expenses_by_shop = self._get_expenses_by_shop(request, selected_year, selected_month, from_date, to_date)
            hotel_stats = self._calculate_hotel_stats(request, selected_year, selected_month, from_date, to_date)
            
            if not base_queryset.exists() and expense_stats['total_expenses'] == 0 and hotel_stats['total_orders'] == 0:
                return self._get_empty_dashboard_data()

            # Get various statistics
            order_stats = self._calculate_order_stats(base_queryset)
            payment_stats = self._calculate_payment_stats(base_queryset)
            payment_type_stats = self._calculate_payment_type_stats(base_queryset)
            orders_by_payment_status = self._get_orders_by_payment_status(base_queryset)

            # Shop-specific statistics
            shop_a_data = self._get_shop_specific_orders(base_queryset, 'Shop A', expense_stats)
            shop_b_data = self._get_shop_specific_orders(base_queryset, 'Shop B', expense_stats)

            # Calculate total business revenue (laundry + hotel)
            total_laundry_revenue = order_stats['total_revenue']
            
            total_hotel_revenue = hotel_stats['total_revenue']
            total_business_revenue = total_laundry_revenue + total_hotel_revenue
            
            total_laundry_expenses = expense_stats['total_expenses']
            total_hotel_expenses = hotel_stats['total_expenses']
            total_business_expenses = total_laundry_expenses + total_hotel_expenses
            
            total_net_profit = total_business_revenue - total_business_expenses

            # Business growth statistics
            business_growth = {
                'total_revenue': total_business_revenue,
                'total_orders': order_stats['total_orders'] + hotel_stats['total_orders'],
                'total_expenses': total_business_expenses,
                'net_profit': total_net_profit
            }

            # Additional analytics
            revenue_by_shop = list(base_queryset.values('shop').annotate(
                total_revenue=Sum('total_price'),
                total_amount_paid=Sum('amount_paid'),
                total_balance=Sum('balance')
            ).order_by('-total_revenue'))

            balance_by_shop = list(base_queryset.values('shop').annotate(
                total_balance=Sum('balance')
            ).order_by('-total_balance'))

            common_customers = list(base_queryset.values(
                'customer__name', 'customer__phone'
            ).annotate(
                order_count=Count('id'),
                total_spent=Sum('total_price'),
                total_paid=Sum('amount_paid'),
                total_balance=Sum('balance')
            ).order_by('-order_count')[:5])

            payment_methods = list(base_queryset.values('payment_type').annotate(
                count=Count('id'),
                total_amount=Sum('total_price'),
                total_paid=Sum('amount_paid'),
                total_balance=Sum('balance')
            ).order_by('-count'))

            order_ids = list(base_queryset.values_list('id', flat=True))
            
            # Use the MultiSelectField processor
            top_services = self._process_multiselect_services(order_ids)
            common_items = self._get_common_items_data(tuple(order_ids))
            service_types_data = self._process_multiselect_services(order_ids)

            # Chart data
            line_chart_data = []
            monthly_order_volume = []
            monthly_expenses_data = []
            monthly_business_growth_data = []

            if not selected_month and not (from_date and to_date):
                user_shops = self.get_user_shops(request)
                if user_shops is None:
                    shops = ['Shop A', 'Shop B']
                else:
                    shops = user_shops

                for shop_name in shops:
                    monthly_data = base_queryset.filter(shop=shop_name).annotate(
                        month=ExtractMonth('delivery_date')
                    ).values('month').annotate(
                        revenue=Coalesce(Sum('total_price'), 0, output_field=DecimalField())
                    ).order_by('month')

                    revenue_by_month = {item['month']: float(item['revenue']) for item in monthly_data}
                    monthly_values = [revenue_by_month.get(month, 0) for month in range(1, 13)]

                    if any(monthly_values):
                        color_seed = shop_name.encode('utf-8')
                        hex_color = hashlib.md5(color_seed).hexdigest()[0:6]
                        line_chart_data.append({
                            'label': shop_name,
                            'data': monthly_values,
                            'borderColor': f'#{hex_color}',
                            'fill': False,
                            'months': MONTHS
                        })

                monthly_order_volume = [
                    base_queryset.filter(delivery_date__month=month).count()
                    for month in range(1, 13)
                ]
                
                monthly_expenses_data = self._get_monthly_expenses_data(request, selected_year)
                monthly_business_growth_data = self._get_monthly_business_growth(request, selected_year)

            return {
                'order_stats': order_stats,
                'payment_stats': payment_stats,
                'payment_type_stats': payment_type_stats,
                'expense_stats': expense_stats,
                'hotel_stats': hotel_stats,
                'business_growth': business_growth,
                'orders_by_payment_status': orders_by_payment_status,
                'revenue_by_shop': revenue_by_shop,
                'balance_by_shop': balance_by_shop,
                'expenses_by_shop': expenses_by_shop,
                'common_customers': common_customers,
                'payment_methods': payment_methods,
                'top_services': top_services,
                'common_items': common_items,
                'service_types': service_types_data,
                'line_chart_data': line_chart_data,
                'monthly_order_volume': monthly_order_volume,
                'monthly_expenses_data': monthly_expenses_data,
                'monthly_business_growth': monthly_business_growth_data,
                'shop_a_stats': shop_a_data['stats'],
                'shop_b_stats': shop_b_data['stats'],
                'shop_a_orders': shop_a_data['orders_by_payment_status'],
                'shop_b_orders': shop_b_data['orders_by_payment_status'],
            }
        
        except Exception as e:
            logger.error(f"Error in get_dashboard_data: {e}")
            return self._get_empty_dashboard_data()
    
    def get_orders_by_payment_status(self, request, payment_status, shop=None, selected_year=None, selected_month=None):
        """
        Get orders filtered by payment status.
        """
        try:
            base_queryset = self._get_base_queryset(request, selected_year, selected_month, shop=shop)
            
            if payment_status == PAYMENT_STATUS_PENDING:
                orders = base_queryset.filter(
                    Q(amount_paid=0) | Q(amount_paid__isnull=True)
                ).select_related('customer').order_by('-delivery_date')
            elif payment_status == PAYMENT_STATUS_PARTIAL:
                orders = base_queryset.filter(
                    Q(amount_paid__gt=0, amount_paid__lt=models.F('total_price')) |
                    Q(balance__gt=0)
                ).select_related('customer').order_by('-delivery_date')
            elif payment_status == PAYMENT_STATUS_COMPLETE:
                orders = base_queryset.filter(
                    Q(amount_paid__gte=models.F('total_price')) |
                    Q(balance=0)
                ).select_related('customer').order_by('-delivery_date')
            elif payment_status == PAYMENT_STATUS_OVERDUE:
                orders = base_queryset.filter(
                    Q(delivery_date__lt=now().date()) & 
                    (Q(amount_paid__lt=models.F('total_price')) | 
                     Q(balance__gt=0) | 
                     Q(amount_paid__isnull=True))
                ).select_related('customer').order_by('-delivery_date')
            else:
                orders = base_queryset.select_related('customer').order_by('-delivery_date')
            
            return orders
            
        except Exception as e:
            logger.error(f"Error in get_orders_by_payment_status: {e}")
            return Order.objects.none()
    
    def sanitize_for_json(self, value):
        """
        Sanitize values for JSON serialization.
        """
        if isinstance(value, str):
            cleaned = ''.join(char for char in value if ord(char) >= 32 or char in '\t\n\r')
            cleaned = cleaned.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
            return cleaned
        elif isinstance(value, (int, float)):
            return value
        elif value is None:
            return None
        else:
            return str(value)
    
    def prepare_dashboard_context(self, request, data, selected_year, selected_month=None, from_date=None, to_date=None, payment_status=None, shop=None):
        """
        Prepare the complete dashboard context for templates.
        """
        # Get available years and shops
        years = Order.objects.filter(
            order_status__in=ACTIVE_ORDER_STATUSES
        ).annotate(
            year=ExtractYear('delivery_date')
        ).values_list('year', flat=True).distinct().order_by('year')

        user_shops = self.get_user_shops(request)
        if user_shops is None:
            available_shops = ['Shop A', 'Shop B']
        else:
            available_shops = user_shops

        # Sanitize data for JSON
        sanitized_revenue_by_shop = [
            {
                'shop': self.sanitize_for_json(item['shop']), 
                'total_revenue': item['total_revenue'],
                'total_amount_paid': item.get('total_amount_paid', 0),
                'total_balance': item.get('total_balance', 0)
            }
            for item in data['revenue_by_shop']
        ]

        sanitized_balance_by_shop = [
            {
                'shop': self.sanitize_for_json(item['shop']), 
                'total_balance': item.get('total_balance', 0)
            }
            for item in data['balance_by_shop']
        ]

        # Fix service labels for MultiSelectField data
        sanitized_top_services = []
        for item in data['top_services']:
            servicetype = item['servicetype']
            # Handle both single services and lists from MultiSelectField
            if isinstance(servicetype, list):
                if len(servicetype) == 1:
                    service_label = servicetype[0]
                else:
                    service_label = ' + '.join(servicetype)
            else:
                service_label = str(servicetype)
            
            sanitized_top_services.append({
                'servicetype': service_label,
                'count': item['count']
            })

        sanitized_common_items = [
            {'itemname': self.sanitize_for_json(item['itemname']), 'count': item['count']}
            for item in data['common_items']
        ]

        # Prepare payment type data for charts - now includes amount collected
        payment_type_stats = data.get('payment_type_stats', {})
        payment_type_labels = []
        payment_type_amounts = []
        payment_type_collected = []
        payment_type_counts = []
        payment_type_colors = ['#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0', '#9966FF']
        
        for i, payment_type in enumerate(PAYMENT_TYPES):
            stats = payment_type_stats.get(payment_type, {'count': 0, 'total_amount': 0, 'amount_collected': 0})
            payment_type_labels.append(payment_type.title())
            payment_type_amounts.append(float(stats['total_amount']))
            payment_type_collected.append(float(stats['amount_collected']))
            payment_type_counts.append(stats['count'])

        # Get correct revenue values for doughnut chart
        laundry_revenue = data['order_stats']['total_revenue']
        hotel_revenue = data['hotel_stats']['total_revenue']
        total_business_revenue = data['business_growth']['total_revenue']

        # Calculate profits
        laundry_profit = data['order_stats']['total_revenue'] - data['expense_stats']['total_expenses']
        hotel_profit = data['hotel_stats']['net_profit']
        total_net_profit = data['business_growth']['net_profit']

        # Build context
        context = {
            'title': 'Business Dashboard',
            'current_year': selected_year,
            'selected_month': selected_month,
            'from_date': from_date,
            'to_date': to_date,
            'payment_status': payment_status,
            'selected_shop': shop,
            'years': list(years),
            'available_shops': available_shops,

            # Core statistics
            'total_revenue': data['order_stats']['total_revenue'],
            'total_orders': data['order_stats']['total_orders'],
            'pending_orders': data['order_stats']['pending_orders'],
            'completed_orders': data['order_stats']['completed_orders'],
            'total_amount_paid': data['order_stats']['total_amount_paid'],
            'total_balance': data['order_stats']['total_balance'],
            
            # Payment statistics - now includes total amounts for each status
            'pending_payments': data['payment_stats']['pending_payments'],
            'partial_payments': data['payment_stats']['partial_payments'],
            'complete_payments': data['payment_stats']['complete_payments'],
            'total_pending_amount': data['payment_stats']['total_pending_amount'],
            'total_partial_amount': data['payment_stats']['total_partial_amount'],
            'total_complete_amount': data['payment_stats']['total_complete_amount'],
            'total_collected_amount': data['payment_stats']['total_collected_amount'],
            'total_balance_amount': data['payment_stats']['total_balance_amount'],

            # Payment type statistics with collected amounts
            'payment_type_stats': payment_type_stats,
            'cash_payments_count': payment_type_stats.get('cash', {}).get('count', 0),
            'cash_payments_amount': payment_type_stats.get('cash', {}).get('total_amount', 0),
            'cash_payments_collected': payment_type_stats.get('cash', {}).get('amount_collected', 0),
            'mpesa_payments_count': payment_type_stats.get('mpesa', {}).get('count', 0),
            'mpesa_payments_amount': payment_type_stats.get('mpesa', {}).get('total_amount', 0),
            'mpesa_payments_collected': payment_type_stats.get('mpesa', {}).get('amount_collected', 0),
            'card_payments_count': payment_type_stats.get('card', {}).get('count', 0),
            'card_payments_amount': payment_type_stats.get('card', {}).get('total_amount', 0),
            'card_payments_collected': payment_type_stats.get('card', {}).get('amount_collected', 0),
            'bank_transfer_payments_count': payment_type_stats.get('bank_transfer', {}).get('count', 0),
            'bank_transfer_payments_amount': payment_type_stats.get('bank_transfer', {}).get('total_amount', 0),
            'bank_transfer_payments_collected': payment_type_stats.get('bank_transfer', {}).get('amount_collected', 0),
            'other_payments_count': payment_type_stats.get('other', {}).get('count', 0),
            'other_payments_amount': payment_type_stats.get('other', {}).get('total_amount', 0),
            'other_payments_collected': payment_type_stats.get('other', {}).get('amount_collected', 0),
            'none_payments_count': payment_type_stats.get('None', {}).get('count', 0),
            'none_payments_amount': payment_type_stats.get('None', {}).get('total_amount', 0),
            'none_payments_collected': payment_type_stats.get('None', {}).get('amount_collected', 0),

            # Expense statistics
            'total_expenses': data['expense_stats']['total_expenses'],
            'shop_a_expenses': data['expense_stats']['shop_a_expenses'],
            'shop_b_expenses': data['expense_stats']['shop_b_expenses'],

            # Hotel statistics
            'hotel_total_orders': data['hotel_stats']['total_orders'],
            'hotel_total_revenue': data['hotel_stats']['total_revenue'],
            'hotel_net_profit': data['hotel_stats']['net_profit'],

            # Total Business Statistics
            'total_business_revenue': total_business_revenue,
            'total_business_expenses': data['business_growth']['total_expenses'],
            'total_net_profit': total_net_profit,

            # Individual business revenues (for doughnut chart)
            'laundry_revenue': laundry_revenue,
            'hotel_revenue': hotel_revenue,

            # Individual business profits
            'laundry_profit': laundry_profit,
            'hotel_profit': hotel_profit,

            # Shop statistics - now includes payment amounts
            'shop_a_revenue': data['shop_a_stats']['revenue'],
            'shop_a_total_orders': data['shop_a_stats']['total_orders'],
            'shop_a_net_profit': data['shop_a_stats']['net_profit'],
            'shop_a_pending_amount': data['shop_a_stats']['total_pending_amount'],
            'shop_a_partial_amount': data['shop_a_stats']['total_partial_amount'],
            'shop_a_complete_amount': data['shop_a_stats']['total_complete_amount'],

            'shop_b_revenue': data['shop_b_stats']['revenue'],
            'shop_b_total_orders': data['shop_b_stats']['total_orders'],
            'shop_b_net_profit': data['shop_b_stats']['net_profit'],
            'shop_b_pending_amount': data['shop_b_stats']['total_pending_amount'],
            'shop_b_partial_amount': data['shop_b_stats']['total_partial_amount'],
            'shop_b_complete_amount': data['shop_b_stats']['total_complete_amount'],

            # Chart data - properly serialized
            'pie_chart_labels': json.dumps([item['shop'] for item in sanitized_revenue_by_shop]),
            'pie_chart_values': json.dumps([float(item['total_revenue']) for item in sanitized_revenue_by_shop]),

            'balance_pie_chart_labels': json.dumps([item['shop'] for item in sanitized_balance_by_shop]),
            'balance_pie_chart_values': json.dumps([float(item['total_balance']) for item in sanitized_balance_by_shop]),

            'services_labels': json.dumps([item['servicetype'] for item in sanitized_top_services]),
            'services_counts': json.dumps([item['count'] for item in sanitized_top_services]),

            'item_labels': json.dumps([item['itemname'] for item in sanitized_common_items]),
            'item_counts': json.dumps([item['count'] for item in sanitized_common_items]),

            # Payment type charts - both total amounts and collected amounts
            'payment_type_labels': json.dumps(payment_type_labels),
            'payment_type_amounts': json.dumps(payment_type_amounts),
            'payment_type_collected': json.dumps(payment_type_collected),
            'payment_type_counts': json.dumps(payment_type_counts),
            'payment_type_colors': json.dumps(payment_type_colors),

            # REVENUE COMPARISON DOUGHNUT CHART - Fixed to show revenue, not profit
            'revenue_comparison_labels': json.dumps(['Laundry Revenue', 'Hotel Revenue']),
            'revenue_comparison_data': json.dumps([float(laundry_revenue), float(hotel_revenue)]),
            'revenue_comparison_colors': json.dumps(['#36A2EB', '#FF6384']),

            # Profit comparison chart (separate from revenue)
            'profit_comparison_labels': json.dumps(['Laundry Profit', 'Hotel Profit']),
            'profit_comparison_data': json.dumps([float(laundry_profit), float(hotel_profit)]),
            'profit_comparison_colors': json.dumps(['#4BC0C0', '#FF9F40']),

            'line_chart_data': json.dumps(data.get('line_chart_data', [])),
            'monthly_order_volume': json.dumps(data.get('monthly_order_volume', [])),
            'monthly_expenses_data': json.dumps(data.get('monthly_expenses_data', [])),
            'monthly_business_growth': json.dumps(data.get('monthly_business_growth', [])),

            'common_customers': data['common_customers'],
        }

        return context