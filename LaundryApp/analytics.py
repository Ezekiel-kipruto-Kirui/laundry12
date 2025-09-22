"""
Analytics and dashboard functionality for LaundryApp.

This module contains all analytics, reporting, and dashboard-related functionality
separated from the main admin configuration for better maintainability.
"""

# Standard library imports
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

# Local imports
from .models import Order, OrderItem

# Setup logger
logger = logging.getLogger(__name__)

# --- Constants ---
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
ACTIVE_ORDER_STATUSES = ['pending', 'processing', 'Completed', 'Delivered/picked']  # Statuses that count as active orders

# Payment status constants
PAYMENT_STATUS_PENDING = 'pending'
PAYMENT_STATUS_PARTIAL = 'partial'
PAYMENT_STATUS_COMPLETE = 'complete'
PAYMENT_STATUS_OVERDUE = 'overdue'


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
                'delivered_orders': 0, 'total_revenue': 0, 'avg_order_value': 0
            },
            'payment_stats': {
                'pending_payments': 0,
                'partial_payments': 0,
                'complete_payments': 0,
                'overdue_payments': 0,
                'total_pending_amount': 0,
                'total_partial_amount': 0,
                'total_collected_amount': 0
            },
            'revenue_by_shop': [],
            'common_customers': [],
            'payment_methods': [],
            'top_services': [],
            'common_items': [],
            'service_types': [],
            'line_chart_data': [],
            'monthly_order_volume': [],
            'shop_a_stats': {
                'revenue': 0, 'total_orders': 0, 'pending_orders': 0, 'completed_orders': 0,
                'pending_payments': 0, 'partial_payments': 0, 'complete_payments': 0
            },
            'shop_b_stats': {
                'revenue': 0, 'total_orders': 0, 'pending_orders': 0, 'completed_orders': 0,
                'pending_payments': 0, 'partial_payments': 0, 'complete_payments': 0
            },
        }
    
    def _get_payment_status(self, order):
        """
        Determine payment status based on order payment information.
        This assumes your Order model has fields like:
        - total_price (total order amount)
        - amount_paid (amount already paid)
        - payment_status (optional field)
        """
        # If order has a payment_status field, use it directly
        if hasattr(order, 'payment_status') and order.payment_status:
            return order.payment_status
        
        # Otherwise, calculate based on amount paid vs total price
        total_price = getattr(order, 'total_price', 0) or 0
        amount_paid = getattr(order, 'amount_paid', 0) or 0
        
        if amount_paid == 0:
            return PAYMENT_STATUS_PENDING
        elif amount_paid < total_price:
            return PAYMENT_STATUS_PARTIAL
        elif amount_paid >= total_price:
            return PAYMENT_STATUS_COMPLETE
        else:
            return PAYMENT_STATUS_PENDING
    
    def _get_base_queryset(self, request, selected_year, selected_month=None, from_date=None, to_date=None, payment_status=None):
        """
        Get the base queryset with proper filtering for active orders, user permissions, and payment status.
        """
        base_queryset = Order.objects.filter(order_status__in=ACTIVE_ORDER_STATUSES)

        # Apply year/month if provided
        if selected_year:
            base_queryset = base_queryset.filter(delivery_date__year=selected_year)
        if selected_month:
            base_queryset = base_queryset.filter(delivery_date__month=selected_month)

        # Apply date range filter if provided
        if from_date and to_date:
            base_queryset = base_queryset.filter(delivery_date__range=[from_date, to_date])

        # Apply payment status filtering if provided
        if payment_status:
            if payment_status == PAYMENT_STATUS_PENDING:
                # Orders with no payments or zero amount paid
                base_queryset = base_queryset.filter(
                    Q(amount_paid=0) | Q(amount_paid__isnull=True)
                )
            elif payment_status == PAYMENT_STATUS_PARTIAL:
                # Orders with partial payments (amount_paid > 0 but < total_price)
                base_queryset = base_queryset.filter(
                    amount_paid__gt=0,
                    amount_paid__lt=models.F('total_price')
                )
            elif payment_status == PAYMENT_STATUS_COMPLETE:
                # Orders with complete payments (amount_paid >= total_price)
                base_queryset = base_queryset.filter(
                    amount_paid__gte=models.F('total_price')
                )
            elif payment_status == PAYMENT_STATUS_OVERDUE:
                # Orders that are overdue (you might need to implement this based on your business logic)
                # This is a placeholder - adjust based on your overdue criteria
                base_queryset = base_queryset.filter(
                    Q(delivery_date__lt=now().date()) & 
                    (Q(amount_paid__lt=models.F('total_price')) | Q(amount_paid__isnull=True))
                )

        # Apply shop filtering if user is not superuser
        user_shops = self.get_user_shops(request)
        if user_shops is not None:
            if user_shops:
                base_queryset = base_queryset.filter(shop__in=user_shops)
            else:
                base_queryset = Order.objects.none()

        return base_queryset
    
    def _calculate_payment_stats(self, base_queryset):
        """
        Calculate comprehensive payment statistics from the base queryset.
        """
        # Aggregate payment statistics
        payment_stats = base_queryset.aggregate(
            total_orders=Count('id'),
            pending_payments=Count('id', filter=Q(amount_paid=0) | Q(amount_paid__isnull=True)),
            partial_payments=Count('id', filter=Q(amount_paid__gt=0, amount_paid__lt=models.F('total_price'))),
            complete_payments=Count('id', filter=Q(amount_paid__gte=models.F('total_price'))),
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
                             then=models.F('total_price') - models.F('amount_paid')),
                        default=0,
                        output_field=DecimalField()
                    )
                ), 0, output_field=DecimalField()
            ),
            total_collected_amount=Coalesce(Sum('amount_paid'), 0, output_field=DecimalField()),
            total_revenue=Coalesce(Sum('total_price'), 0, output_field=DecimalField())
        )
        
        # Calculate overdue payments (orders with delivery date passed but not fully paid)
        overdue_stats = base_queryset.filter(
            delivery_date__lt=now().date()
        ).aggregate(
            overdue_payments=Count('id', filter=Q(amount_paid__lt=models.F('total_price'))),
            total_overdue_amount=Coalesce(
                Sum(
                    Case(
                        When(Q(amount_paid__lt=models.F('total_price')), 
                             then=models.F('total_price') - models.F('amount_paid')),
                        default=0,
                        output_field=DecimalField()
                    )
                ), 0, output_field=DecimalField()
            )
        )
        
        payment_stats.update(overdue_stats)
        
        return payment_stats
    
    @lru_cache(maxsize=32)
    def _get_common_items_data(self, order_ids):
        order_item_data = OrderItem.objects.filter(order_id__in=order_ids)
        all_items = []
        for item in order_item_data.only('itemname'):
            if item.itemname:
                item_list = [i.strip() for i in item.itemname.split(',') if i.strip()]
                all_items.extend(item_list)
        item_counter = Counter(all_items)
        return [{'itemname': item, 'count': count} for item, count in item_counter.most_common(5)]
    
    def get_dashboard_data(self, request, selected_year, selected_month=None, from_date=None, to_date=None, payment_status=None):
        """
        Fetch comprehensive dashboard data with optimized queries and shop-based filtering.
        Supports year/month filtering, from-to date range, and payment status filtering.
        """
        try:
            base_queryset = self._get_base_queryset(request, selected_year, selected_month, from_date, to_date, payment_status)
            
            if not base_queryset.exists():
                return self._get_empty_dashboard_data()

            # Get order statistics
            order_stats = base_queryset.aggregate(
                total_orders=Count('id'),
                pending_orders=Count('id', filter=Q(order_status='pending')),
                completed_orders=Count('id', filter=Q(order_status='Completed')),
                delivered_orders=Count('id', filter=Q(order_status='Delivered/picked')),
                total_revenue=Coalesce(Sum('total_price'), 0, output_field=DecimalField()),
                avg_order_value=Coalesce(Avg('total_price'), 0, output_field=DecimalField())
            )

            # Get payment statistics
            payment_stats = self._calculate_payment_stats(base_queryset)

            # Shop-specific statistics with payment info
            shop_a_stats = base_queryset.filter(shop='Shop A').aggregate(
                revenue=Coalesce(Sum('total_price'), 0, output_field=DecimalField()),
                total_orders=Count('id'),
                pending_orders=Count('id', filter=Q(order_status='pending')),
                completed_orders=Count('id', filter=Q(order_status='Completed')),
                pending_payments=Count('id', filter=Q(amount_paid=0) | Q(amount_paid__isnull=True)),
                partial_payments=Count('id', filter=Q(amount_paid__gt=0, amount_paid__lt=models.F('total_price'))),
                complete_payments=Count('id', filter=Q(amount_paid__gte=models.F('total_price')))
            )

            shop_b_stats = base_queryset.filter(shop='Shop B').aggregate(
                revenue=Coalesce(Sum('total_price'), 0, output_field=DecimalField()),
                total_orders=Count('id'),
                pending_orders=Count('id', filter=Q(order_status='pending')),
                completed_orders=Count('id', filter=Q(order_status='Completed')),
                pending_payments=Count('id', filter=Q(amount_paid=0) | Q(amount_paid__isnull=True)),
                partial_payments=Count('id', filter=Q(amount_paid__gt=0, amount_paid__lt=models.F('total_price'))),
                complete_payments=Count('id', filter=Q(amount_paid__gte=models.F('total_price')))
            )

            # Additional analytics data
            revenue_by_shop = list(base_queryset.values('shop').annotate(
                total_revenue=Sum('total_price')
            ).order_by('-total_revenue'))

            common_customers = list(base_queryset.values(
                'customer__name', 'customer__phone'
            ).annotate(
                order_count=Count('id'),
                total_spent=Sum('total_price')
            ).order_by('-order_count')[:5])

            payment_methods = list(base_queryset.values('payment_type').annotate(
                count=Count('id')
            ).order_by('-count'))

            order_ids = list(base_queryset.values_list('id', flat=True))
            
            top_services = list(OrderItem.objects.filter(
                order_id__in=order_ids
            ).values('servicetype').annotate(
                count=Count('id')
            ).order_by('-count')[:5])

            common_items = self._get_common_items_data(tuple(order_ids))

            service_types = list(OrderItem.objects.filter(
                order_id__in=order_ids
            ).values('servicetype').annotate(
                count=Count('id')
            ).order_by('-count'))

            line_chart_data = []
            monthly_order_volume = []

            if not selected_month and not (from_date and to_date):
                user_shops = self.get_user_shops(request)
                if user_shops is None:
                    shops = [choice[0] for choice in Order._meta.get_field('shop').choices]
                else:
                    shops = user_shops

                for shop in shops:
                    monthly_data = base_queryset.filter(shop=shop).annotate(
                        month=ExtractMonth('delivery_date')
                    ).values('month').annotate(
                        revenue=Coalesce(Sum('total_price'), 0, output_field=DecimalField())
                    ).order_by('month')

                    revenue_by_month = {item['month']: float(item['revenue']) for item in monthly_data}
                    monthly_values = [revenue_by_month.get(month, 0) for month in range(1, 13)]

                    if any(monthly_values):
                        color_seed = shop.encode('utf-8')
                        hex_color = hashlib.md5(color_seed).hexdigest()[0:6]
                        line_chart_data.append({
                            'label': shop,
                            'data': monthly_values,
                            'borderColor': f'#{hex_color}',
                            'fill': False,
                            'months': MONTHS
                        })

                monthly_order_volume = [
                    base_queryset.filter(delivery_date__month=month).count()
                    for month in range(1, 13)
                ]

            return {
                'order_stats': order_stats,
                'payment_stats': payment_stats,
                'revenue_by_shop': revenue_by_shop,
                'common_customers': common_customers,
                'payment_methods': payment_methods,
                'top_services': top_services,
                'common_items': common_items,
                'service_types': service_types,
                'line_chart_data': line_chart_data,
                'monthly_order_volume': monthly_order_volume,
                'shop_a_stats': shop_a_stats,
                'shop_b_stats': shop_b_stats,
            }
        
        except Exception as e:
            logger.error(f"Error in get_dashboard_data: {e}")
            return self._get_empty_dashboard_data()
    
    def sanitize_for_json(self, value):
        if isinstance(value, str):
            cleaned = ''.join(char for char in value if ord(char) >= 32 or char in '\t\n\r')
            cleaned = cleaned.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
            return cleaned
        elif isinstance(value, (int, float)):
            return value
        elif value is None:
            return None
        else:
            return self.sanitize_for_json(str(value))
    
    def prepare_dashboard_context(self, request, data, selected_year, selected_month=None, from_date=None, to_date=None, payment_status=None):
        years = Order.objects.filter(
            order_status__in=ACTIVE_ORDER_STATUSES
        ).annotate(
            year=ExtractYear('delivery_date')
        ).values_list('year', flat=True).distinct().order_by('year')

        sanitized_revenue_by_shop = [
            {'shop': self.sanitize_for_json(item['shop']), 'total_revenue': item['total_revenue']}
            for item in data['revenue_by_shop']
        ]

        sanitized_top_services = [
            {'servicetype': self.sanitize_for_json(item['servicetype']), 'count': item['count']}
            for item in data['top_services']
        ]

        sanitized_common_items = [
            {'itemname': self.sanitize_for_json(item['itemname']), 'count': item['count']}
            for item in data['common_items']
        ]

        sanitized_payment_methods = [
            {'payment_type': self.sanitize_for_json(item['payment_type']), 'count': item['count']}
            for item in data['payment_methods']
        ]

        sanitized_service_types = [
            {'servicetype': self.sanitize_for_json(item['servicetype']), 'count': item['count']}
            for item in data['service_types']
        ]

        sanitized_line_chart_data = []
        for series in data['line_chart_data']:
            sanitized_series = series.copy()
            sanitized_series['label'] = self.sanitize_for_json(series['label'])
            sanitized_line_chart_data.append(sanitized_series)

        context = {
            'title': 'Business Dashboard',
            'current_year': selected_year,
            'selected_month': selected_month,
            'from_date': from_date,
            'to_date': to_date,
            'payment_status': payment_status,
            'years': list(years),

            # Order statistics
            'total_revenue': data['order_stats']['total_revenue'],
            'total_orders': data['order_stats']['total_orders'],
            'pending_orders': data['order_stats']['pending_orders'],
            'completed_orders': data['order_stats']['completed_orders'],
            'delivered_orders': data['order_stats']['delivered_orders'],
            'avg_order_value': data['order_stats']['avg_order_value'],

            # Payment statistics
            'pending_payments': data['payment_stats']['pending_payments'],
            'partial_payments': data['payment_stats']['partial_payments'],
            'complete_payments': data['payment_stats']['complete_payments'],
            'overdue_payments': data['payment_stats'].get('overdue_payments', 0),
            'total_pending_amount': data['payment_stats']['total_pending_amount'],
            'total_partial_amount': data['payment_stats']['total_partial_amount'],
            'total_collected_amount': data['payment_stats']['total_collected_amount'],
            'total_overdue_amount': data['payment_stats'].get('total_overdue_amount', 0),

            # Shop A statistics
            'shop_a_revenue': data['shop_a_stats']['revenue'],
            'shop_a_total_orders': data['shop_a_stats']['total_orders'],
            'shop_a_pending_orders': data['shop_a_stats']['pending_orders'],
            'shop_a_completed_orders': data['shop_a_stats']['completed_orders'],
            'shop_a_pending_payments': data['shop_a_stats']['pending_payments'],
            'shop_a_partial_payments': data['shop_a_stats']['partial_payments'],
            'shop_a_complete_payments': data['shop_a_stats']['complete_payments'],

            # Shop B statistics
            'shop_b_revenue': data['shop_b_stats']['revenue'],
            'shop_b_total_orders': data['shop_b_stats']['total_orders'],
            'shop_b_pending_orders': data['shop_b_stats']['pending_orders'],
            'shop_b_completed_orders': data['shop_b_stats']['completed_orders'],
            'shop_b_pending_payments': data['shop_b_stats']['pending_payments'],
            'shop_b_partial_payments': data['shop_b_stats']['partial_payments'],
            'shop_b_complete_payments': data['shop_b_stats']['complete_payments'],

            # Chart data
            'pie_chart_labels': json.dumps([item['shop'] for item in sanitized_revenue_by_shop]),
            'pie_chart_values': json.dumps([float(item['total_revenue']) for item in sanitized_revenue_by_shop]),

            'line_chart_data': json.dumps(sanitized_line_chart_data),

            'services_labels': json.dumps([item['servicetype'] for item in sanitized_top_services]),
            'services_counts': json.dumps([item['count'] for item in sanitized_top_services]),

            'item_labels': json.dumps([item['itemname'] for item in sanitized_common_items]),
            'item_counts': json.dumps([item['count'] for item in sanitized_common_items]),

            'payment_method_labels': json.dumps([item['payment_type'] for item in sanitized_payment_methods]),
            'payment_method_counts': json.dumps([item['count'] for item in sanitized_payment_methods]),

            'service_type_labels': json.dumps([item['servicetype'] for item in sanitized_service_types]),
            'service_type_counts': json.dumps([item['count'] for item in sanitized_service_types]),

            'monthly_order_volume': json.dumps(data['monthly_order_volume']),
            'common_customers': data['common_customers'],
        }

        return context


def should_count_order(order_status):
    return order_status in ACTIVE_ORDER_STATUSES


from django.db.models.signals import post_save
from django.dispatch import receiver

@receiver(post_save, sender=Order)
def clear_analytics_cache_on_order_change(sender, instance, **kwargs):
    try:
        dashboard_analytics = DashboardAnalytics(None)
        dashboard_analytics._get_common_items_data.cache_clear()
    except Exception as e:
        logger.error(f"Error clearing analytics cache: {e}")