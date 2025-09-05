from django.shortcuts import render, redirect 
from .models import Order


from django.db.models import  Sum
def general_dashboard(self, request):
        if not request.user.is_authenticated:
            return redirect('admin:login')
        
        # Get user's shops
        user_shops = self.get_user_shops(request)
        
        # Base queryset
        if request.user.is_superuser:
            # Superuser sees all orders
            orders = Order.objects.all()
        elif user_shops:
            # Staff sees only their shop's orders
            orders = Order.objects.filter(shop__in=user_shops)
        else:
            # Users with no shop assignments see nothing
            orders = Order.objects.none()
        
        # Calculate stats
        total_orders = orders.count()
        pending_orders = orders.filter(order_status='Pending').count()
        processing_orders = orders.filter(order_status='Processing').count()
        completed_orders = orders.filter(order_status='Completed').count()
        delivered_orders = orders.filter(order_status='Delivered').count()
        
        # Get recent orders
        recent_orders = orders.select_related('customer').order_by('-created_at')[:10]
        
        # For superusers, get shop performance data
        shop_performance = None
        if request.user.is_superuser:
            shop_performance = {}
            shops = Order.objects.values_list('shop', flat=True).distinct()
            for shop in shops:
                if shop:  # Ensure shop is not empty
                    shop_orders = Order.objects.filter(shop=shop)
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
            'processing_orders': processing_orders,
            'completed_orders': completed_orders,
            'delivered_orders': delivered_orders,
            'recent_orders': recent_orders,
            'shop_performance': shop_performance,
            **self.admin_site.each_context(request),
        }
      
        return render(request, 'Admin/dashboard.html', context)
        
