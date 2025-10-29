# LaundryApp/middleware.py
from django.shortcuts import redirect
from django.urls import reverse

class ActiveShopMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Allow unauthenticated users (login/register)
        if not request.user.is_authenticated:
            return self.get_response(request)

        # Allow superusers to access everything without selecting a shop
        if request.user.is_superuser:
            return self.get_response(request)

        # Define allowed paths
        allowed_paths = [
            reverse('select_shop'),
            reverse('logout'),
        ]

        # ✅ Skip admin area
        if request.path.startswith('/admin/') or request.path in allowed_paths:
            return self.get_response(request)

        # ✅ Check if session has active shop (use correct key name)
        active_shop = request.session.get('active_shop_id')

        # If no active shop in session, force selection
        if not active_shop:
            return redirect('select_shop')

        # ✅ If user is on select_shop but already has an active shop → redirect to dashboard
        if request.path == reverse('select_shop') and active_shop:
            if active_shop == 'Shop A':
                return redirect('laundry:Laundrydashboard')
            elif active_shop == 'Shop B':
                return redirect('laundry:Laundrydashboard')
            else:
                return redirect('hotel:order_list')
            return redirect('dashboard')  # or your main landing page

        return self.get_response(request)
