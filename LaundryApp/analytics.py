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
ACTIVE_ORDER_STATUSES = ['pending', 'processing', 'Completed', 'Delivered']  # Statuses that count as active orders


class DashboardAnalytics:
    """
    Handles all analytics and dashboard-related functionality for the laundry management system.
    
    This class provides methods for generating dashboard data, statistics, and visualizations
    while respecting shop-based permissions and excluding orders with certain statuses.
    """
    
    def __init__(self, admin_instance):
        """
        Initialize with a reference to the admin instance for permission handling.
        
        Args:
            admin_instance: The admin instance that provides shop permission methods.
        """
        self.admin_instance = admin_instance
    
    def get_user_shops(self, request):
        """
        Get the shops that the user has access to based on their groups.
        
        Delegates to the admin instance's method.
        """
        return self.admin_instance.get_user_shops(request)
    
    def _get_empty_dashboard_data(self):
        """Return empty dashboard data structure."""
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
    
    def _get_base_queryset(self, request, selected_year, selected_month=None):
        """
        Get the base queryset with proper filtering for active orders and user permissions.
        
        Args:
            request: The current request object.
            selected_year: The year to filter data by.
            selected_month: The month to filter data by (optional).
            
        Returns:
            QuerySet: Filtered queryset of active orders.
        """
        # Base queryset with year filter and active status filter
        base_queryset = Order.objects.filter(
            delivery_date__year=selected_year,
            order_status__in=ACTIVE_ORDER_STATUSES  # Only include active orders
        )
        
        if selected_month:
            base_queryset = base_queryset.filter(delivery_date__month=selected_month)

        # Apply shop filtering if user is not superuser
        user_shops = self.get_user_shops(request)
        if user_shops is not None:  # Not superuser
            if user_shops:  # Has specific shops
                base_queryset = base_queryset.filter(shop__in=user_shops)
            else:  # No shop access
                base_queryset = Order.objects.none()  # Return empty queryset

        return base_queryset
    
    @lru_cache(maxsize=32)
    def _get_common_items_data(self, order_ids):
        """
        Get common items data with caching for better performance.
        
        Args:
            order_ids: List of order IDs to filter by.
            
        Returns:
            list: Common items with their counts.
        """
        order_item_data = OrderItem.objects.filter(order_id__in=order_ids)
        
        all_items = []
        for item in order_item_data.only('itemname'):
            if item.itemname:
                item_list = [i.strip() for i in item.itemname.split(',') if i.strip()]
                all_items.extend(item_list)

        # Count item occurrences
        item_counter = Counter(all_items)
        return [{'itemname': item, 'count': count} for item, count in item_counter.most_common(5)]
    
    def get_dashboard_data(self, request, selected_year, selected_month=None):
        """
        Fetch comprehensive dashboard data with optimized queries and shop-based filtering.
        Only includes orders with active statuses (not cancelled or other inactive statuses).
        
        Args:
            request: The current request object.
            selected_year: The year to filter data by.
            selected_month: The month to filter data by (optional).
            
        Returns:
            dict: Comprehensive dashboard data including statistics and analytics.
        """
        try:
            # Get base queryset with proper filtering
            base_queryset = self._get_base_queryset(request, selected_year, selected_month)
            
            # Return empty data if no orders match the criteria
            if not base_queryset.exists():
                return self._get_empty_dashboard_data()

            # Single aggregation query for order statistics
            order_stats = base_queryset.aggregate(
                total_orders=Count('id'),
                pending_orders=Count('id', filter=Q(order_status='pending')),
                completed_orders=Count('id', filter=Q(order_status='Completed')),
                delivered_orders=Count('id', filter=Q(order_status='Delivered')),
                total_revenue=Coalesce(Sum('total_price'), 0, output_field=DecimalField()),
                avg_order_value=Coalesce(Avg('total_price'), 0, output_field=DecimalField())
            )

            # Shop-specific statistics
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

            # Optimized queries with proper aggregation
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

            # OrderItem related data - optimized
            order_ids = list(base_queryset.values_list('id', flat=True))
            
            # Get top services
            top_services = list(OrderItem.objects.filter(
                order_id__in=order_ids
            ).values('servicetype').annotate(
                count=Count('id')
            ).order_by('-count')[:5])

            # Get common items using cached method
            common_items = self._get_common_items_data(tuple(order_ids))

            service_types = list(OrderItem.objects.filter(
                order_id__in=order_ids
            ).values('servicetype').annotate(
                count=Count('id')
            ).order_by('-count'))

            # Monthly data for charts
            line_chart_data = []
            monthly_order_volume = []

            if not selected_month:
                # Get user shops for chart data
                user_shops = self.get_user_shops(request)
                if user_shops is None:  # Superuser - show all shops
                    shops = [choice[0] for choice in Order._meta.get_field('shop').choices]
                else:  # Regular user - show only their shops
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
            # Log error and return empty data to prevent template errors
            logger.error(f"Error in get_dashboard_data: {e}")
            return self._get_empty_dashboard_data()
    
    def sanitize_for_json(self, value):
        """
        Remove control characters and escape special characters for JSON safety.
        
        Args:
            value: The value to sanitize.
            
        Returns:
            Sanitized value safe for JSON serialization.
        """
        if isinstance(value, str):
            # Remove control characters (ASCII 0-31 except tab, newline, carriage return)
            cleaned = ''.join(char for char in value if ord(char) >= 32 or char in '\t\n\r')
            # Escape backslashes and quotes for JSON safety
            cleaned = cleaned.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
            return cleaned
        elif isinstance(value, (int, float)):
            return value
        elif value is None:
            return None
        else:
            # Convert to string and sanitize
            return self.sanitize_for_json(str(value))
    
    def prepare_dashboard_context(self, request, data, selected_year, selected_month=None):
        """
        Prepare the context data for rendering the dashboard template.
        
        Args:
            request: The current request object.
            data: The dashboard data from get_dashboard_data.
            selected_year: The selected year for filtering.
            selected_month: The selected month for filtering (optional).
            
        Returns:
            dict: Context data ready for template rendering.
        """
        # Get available years for the filter dropdown (only active orders)
        years = Order.objects.filter(
            order_status__in=ACTIVE_ORDER_STATUSES
        ).annotate(
            year=ExtractYear('delivery_date')
        ).values_list('year', flat=True).distinct().order_by('year')

        # Sanitize data for JSON serialization
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

        # Sanitize line chart data labels
        sanitized_line_chart_data = []
        for series in data['line_chart_data']:
            sanitized_series = series.copy()
            sanitized_series['label'] = self.sanitize_for_json(series['label'])
            sanitized_line_chart_data.append(sanitized_series)

        context = {
            'title': 'Business Dashboard',
            'current_year': selected_year,
            'selected_month': selected_month,
            'years': list(years),

            'total_revenue': data['order_stats']['total_revenue'],
            'total_orders': data['order_stats']['total_orders'],
            'pending_orders': data['order_stats']['pending_orders'],
            'completed_orders': data['order_stats']['completed_orders'],
            'delivered_orders': data['order_stats']['delivered_orders'],
            'avg_order_value': data['order_stats']['avg_order_value'],

            # Shop-specific data
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


# Utility function to check if an order should be counted in analytics
def should_count_order(order_status):
    """
    Check if an order with the given status should be counted in analytics.
    
    Args:
        order_status: The status of the order.
        
    Returns:
        bool: True if the order should be counted, False otherwise.
    """
    return order_status in ACTIVE_ORDER_STATUSES


# Signal handler to update analytics when order status changes
from django.db.models.signals import post_save
from django.dispatch import receiver

@receiver(post_save, sender=Order)
def clear_analytics_cache_on_order_change(sender, instance, **kwargs):
    """
    Clear analytics cache when an order is saved (status changed).
    This ensures the dashboard shows up-to-date information.
    """
    try:
        # Clear the common items cache
        dashboard_analytics = DashboardAnalytics(None)
        dashboard_analytics._get_common_items_data.cache_clear()
    except Exception as e:
        logger.error(f"Error clearing analytics cache: {e}")