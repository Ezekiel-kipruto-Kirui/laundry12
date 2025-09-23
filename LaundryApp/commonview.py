from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required

@login_required
def redirect_after_login(request):
    # If you are using a custom field `app_type`
    if hasattr(request.user, 'app_type'):
        if request.user.app_type == 'laundry':
            return redirect('laundry:Laundrydashboard')  # update with your real url name
        elif request.user.app_type == 'hotel':
            return redirect('hotel:category_list')
    if request.user.is_superuser:
        return redirect('laundry:dashboard')



    return redirect('login')
