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
from django.db.models import (
    Avg, Count, DecimalField, Q, Sum
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
            'revenue_by_shop': [],
            'common_customers': [],
            'payment_methods': [],
            'top_services': [],
            'common_items': [],
            'service_types': [],
            'line_chart_data': [],
            'monthly_order_volume': [],
            'shop_a_stats': {
                'revenue': 0, 'total_orders': 0, 'pending_orders': 0, 'completed_orders': 0
            },
            'shop_b_stats': {
                'revenue': 0, 'total_orders': 0, 'pending_orders': 0, 'completed_orders': 0
            },
        }
    
    def _get_base_queryset(self, request, selected_year, selected_month=None, from_date=None, to_date=None):
        """
        Get the base queryset with proper filtering for active orders and user permissions.
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

        # Apply shop filtering if user is not superuser
        user_shops = self.get_user_shops(request)
        if user_shops is not None:
            if user_shops:
                base_queryset = base_queryset.filter(shop__in=user_shops)
            else:
                base_queryset = Order.objects.none()

        return base_queryset
    
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
    
    def get_dashboard_data(self, request, selected_year, selected_month=None, from_date=None, to_date=None):
        """
        Fetch comprehensive dashboard data with optimized queries and shop-based filtering.
        Supports year/month filtering and from-to date range.
        """
        try:
            base_queryset = self._get_base_queryset(request, selected_year, selected_month, from_date, to_date)
            
            if not base_queryset.exists():
                return self._get_empty_dashboard_data()

            order_stats = base_queryset.aggregate(
                total_orders=Count('id'),
                pending_orders=Count('id', filter=Q(order_status='pending')),
                completed_orders=Count('id', filter=Q(order_status='Completed')),
                delivered_orders=Count('id', filter=Q(order_status='Delivered/picked')),
                total_revenue=Coalesce(Sum('total_price'), 0, output_field=DecimalField()),
                avg_order_value=Coalesce(Avg('total_price'), 0, output_field=DecimalField())
            )

            shop_a_stats = base_queryset.filter(shop='Shop A').aggregate(
                revenue=Coalesce(Sum('total_price'), 0, output_field=DecimalField()),
                total_orders=Count('id'),
                pending_orders=Count('id', filter=Q(order_status='pending')),
                completed_orders=Count('id', filter=Q(order_status='Completed'))
            )

            shop_b_stats = base_queryset.filter(shop='Shop B').aggregate(
                revenue=Coalesce(Sum('total_price'), 0, output_field=DecimalField()),
                total_orders=Count('id'),
                pending_orders=Count('id', filter=Q(order_status='pending')),
                completed_orders=Count('id', filter=Q(order_status='Completed'))
            )

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
    
    def prepare_dashboard_context(self, request, data, selected_year, selected_month=None, from_date=None, to_date=None):
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
            'years': list(years),

            'total_revenue': data['order_stats']['total_revenue'],
            'total_orders': data['order_stats']['total_orders'],
            'pending_orders': data['order_stats']['pending_orders'],
            'completed_orders': data['order_stats']['completed_orders'],
            'delivered_orders': data['order_stats']['delivered_orders'],
            'avg_order_value': data['order_stats']['avg_order_value'],

            'shop_a_revenue': data['shop_a_stats']['revenue'],
            'shop_a_total_orders': data['shop_a_stats']['total_orders'],
            'shop_a_pending_orders': data['shop_a_stats']['pending_orders'],
            'shop_a_completed_orders': data['shop_a_stats']['completed_orders'],

            
            'shop_b_revenue': data['shop_b_stats']['revenue'],
            'shop_b_total_orders': data['shop_b_stats']['total_orders'],
            'shop_b_pending_orders': data['shop_b_stats']['pending_orders'],
            'shop_b_completed_orders': data['shop_b_stats']['completed_orders'],

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
