from django.shortcuts import redirect,render
from django.contrib.auth.decorators import login_required
from datetime import datetime
from django.db.models import  Sum
from .models import Customer,OrderItem





def redirect_after_login(request):
    # If you are using a custom field `app_type`
    
    # if hasattr(request.user, 'app_type'):
    #     if request.user.app_type == 'laundry':
    #         return redirect('laundry:Laundrydashboard')  # update with your real url name
    #     elif request.user.app_type == 'hotel' and not request.user.is_superuser:
    #         return redirect('hotel:category_list')
    if request.user.is_superuser :
        return redirect('laundry:dashboard')
    else:
        return redirect('laundry:Laundrydashboard')
   
    return redirect('login')
def home (request):
    startyear = 2022
    total_garments = OrderItem.objects.aggregate(total=Sum('quantity'))['total'] or 0
    customers = (Customer.objects.all()).count()
    current_year = datetime.now().year
    yearsinservice = current_year-startyear
    return render(request,'home.html',{'current_year':current_year,'customers':customers,'yearsinservice':yearsinservice,'total_garments':total_garments})
