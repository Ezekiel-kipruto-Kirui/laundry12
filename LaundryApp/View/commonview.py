from django.shortcuts import redirect,render
from django.contrib.auth.decorators import login_required
from datetime import datetime
from django.db.models import  Sum
from ..models import shoptype



def select_shop(request):
    if request.user.is_superuser:
        return redirect('laundry:dashboard')
    if request.method == "POST":
        shop_id = request.POST.get("shop")
        if shoptype.objects.filter(id=shop_id).exists():
            selected = shoptype.objects.get(id=shop_id)
            request.session["active_shop_id"] = shop_id
            request.session["active_shop_name"] = selected.shoptype

            # ✅ Redirect user to correct area
            if selected.shoptype == "Hotel":
                return redirect("hotel:order_list")
            elif selected.shoptype == "Shop A":
                return redirect("laundry:Laundrydashboard")
            elif selected.shoptype == "Shop B":
                return redirect("laundry:Laundrydashboard")

    shops = shoptype.objects.all()
    return render(request, "select_shop.html", {"shops": shops})


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

