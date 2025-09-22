from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from .models import Business
from .forms import BusinessForm

@login_required
def business_list(request):
    businesses = Business.objects.all().order_by("name")
    return render(request, "businesses/business_list.html", {"businesses": businesses})

@login_required
def create_business(request):
    if request.method == "POST":
        form = BusinessForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Business created successfully!")
            return redirect("laundry:business_list")
    else:
        form = BusinessForm()
    return render(request, "businesses/create_business.html", {"form": form})

@login_required
def edit_business(request, business_id):
    business = get_object_or_404(Business, id=business_id)
    if request.method == "POST":
        form = BusinessForm(request.POST, instance=business)
        if form.is_valid():
            form.save()
            messages.success(request, "Business updated successfully!")
            return redirect("laundry:business_list")
    else:
        form = BusinessForm(instance=business)
    return render(request, "businesses/edit_business.html", {"form": form, "business": business})

@login_required
def delete_business(request, business_id):
    business = get_object_or_404(Business, id=business_id)
    if request.method == "POST":
        business.delete()
        messages.success(request, "Business deleted successfully!")
        return redirect("laundry:business_list")
    return render(request, "businesses/delete_business.html", {"business": business})
