from django.http import JsonResponse
from django.db.models import Sum, Count
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from .models import Order, OrderItem

@login_required
@require_http_methods(["GET"])
def debug_orders_revenue(request):
    """
    Simple debug endpoint to get exact order counts and revenue
    """
    try:
        # Get all orders (no filters)
        all_orders = Order.objects.all()
        
        # Basic counts
        total_orders_count = all_orders.count()
        
        # Revenue calculations
        total_revenue = all_orders.aggregate(
            total=Sum('total_price')
        )['total'] or 0
        
        total_amount_paid = all_orders.aggregate(
            total=Sum('amount_paid')
        )['total'] or 0
        
        total_balance = all_orders.aggregate(
            total=Sum('balance')
        )['total'] or 0
        
        # Count by status
        status_counts = all_orders.values('order_status').annotate(
            count=Count('id'),
            revenue=Sum('total_price'),
            paid=Sum('amount_paid'),
            balance_sum=Sum('balance')
        ).order_by('order_status')
        
        # Count by payment status
        payment_status_counts = all_orders.values('payment_status').annotate(
            count=Count('id'),
            revenue=Sum('total_price'),
            paid=Sum('amount_paid'),
            balance_sum=Sum('balance')
        ).order_by('payment_status')
        
        # Count by shop
        shop_counts = all_orders.values('shop').annotate(
            count=Count('id'),
            revenue=Sum('total_price'),
            paid=Sum('amount_paid'),
            balance_sum=Sum('balance')
        ).order_by('shop')
        
        # Get some sample orders to verify calculations
        sample_orders = list(all_orders.values(
            'uniquecode', 'order_status', 'payment_status', 'shop',
            'total_price', 'amount_paid', 'balance'
        )[:5])
        
        # Also check OrderItems to see if there's any discrepancy
        order_items_total = OrderItem.objects.aggregate(
            total=Sum('total_item_price')
        )['total'] or 0
        
        order_items_count = OrderItem.objects.count()
        
        response_data = {
            'summary': {
                'total_orders': total_orders_count,
                'total_revenue': float(total_revenue),
                'total_amount_paid': float(total_amount_paid),
                'total_balance': float(total_balance),
                'order_items_total': float(order_items_total),
                'order_items_count': order_items_count,
                'revenue_discrepancy': float(total_revenue - order_items_total),
            },
            'by_status': list(status_counts),
            'by_payment_status': list(payment_status_counts),
            'by_shop': list(shop_counts),
            'sample_orders': sample_orders,
            'calculations_verified': abs(total_revenue - order_items_total) < 0.01,  # Allow small rounding difference
        }
        
        return JsonResponse(response_data)
        
    except Exception as e:
        return JsonResponse({
            'error': str(e),
            'message': 'Error calculating order statistics'
        }, status=500)