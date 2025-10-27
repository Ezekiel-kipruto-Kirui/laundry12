def active_shop(request):
    return {
        'active_shop_name': request.session.get('active_shop_name', None)
    }
