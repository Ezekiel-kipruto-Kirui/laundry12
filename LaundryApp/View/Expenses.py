
from django.shortcuts import render, redirect, get_object_or_404

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Avg
from django.utils import timezone
from datetime import datetime

from django.contrib.auth import login as auth_login, logout as auth_logout
from ..models import (
   
    ExpenseField, 
    ExpenseRecord, 
   
  
    )
from ..forms import ( 
    
    ExpenseFieldForm,
    ExpenseRecordForm,
   
)
from HotelApp.models import HotelExpenseRecord
from ..resource import OrderResource
from ..views import get_user_shops




@login_required
def create_expense_field(request):
    default_expenses = [
        "Electricity Token",
        "Soap",
        "Softener",
        "Bleach",
        "Stain removers",
        "Laundry Bags",
        "Hangers",
        "Laundry Starch",
        "Rent",
        "Salaries",
        "Delivery fees",
        "Tags",
        "Machine service fee",
    ]

    if request.method == "POST":
        # Case 1: Create default categories (for single business)
        if 'create_defaults' in request.POST:
            created_count = 0
            for label in default_expenses:
                obj, created = ExpenseField.objects.get_or_create(label=label)
                if created:
                    created_count += 1

            if created_count > 0:
                messages.success(request, f"Successfully created {created_count} default expense categories!")
            else:
                messages.info(request, "All default expense categories already exist. You can still add custom expenses below.")

            # Instead of redirecting away, re-render the page so user can add custom ones
            form = ExpenseFieldForm()
            return render(request, "expenses/create_expense_field.html", {
                "form": form,
                "default_expenses": default_expenses
            })

        # Case 2: Manual form submission for custom expense
        form = ExpenseFieldForm(request.POST)
        if form.is_valid():
            label = form.cleaned_data.get("label")

            # Prevent duplicates of existing ones (default or not)
            if ExpenseField.objects.filter(label__iexact=label).exists():
                messages.warning(request, f"'{label}' already exists as an expense category.")
            else:
                form.save()
                messages.success(request, f"Expense field '{label}' created successfully!")
                return redirect("laundry:expense_field_list")
    else:
        form = ExpenseFieldForm()

    return render(request, "expenses/create_expense_field.html", {
        "form": form,
        "default_expenses": default_expenses
    })



@login_required
def expense_field_list(request):
    fields = ExpenseField.objects.all()
    return render(request, "expenses/expense_field_list.html", {"fields": fields})


@login_required
def edit_expense_field(request, field_id):
    field = get_object_or_404(ExpenseField, id=field_id)
    if request.method == "POST":
        form = ExpenseFieldForm(request.POST, instance=field)
        if form.is_valid():
            form.save()
            messages.success(request, "Expense field updated successfully!")
            return redirect("laundry:expense_field_list")
    else:
        form = ExpenseFieldForm(instance=field)
    return render(request, "expenses/edit_expense_field.html", {"form": form, "field": field})


@login_required
def delete_expense_field(request, field_id):
    field = get_object_or_404(ExpenseField, id=field_id)
    if request.method == "POST":
        field.delete()
        messages.success(request, "Expense field deleted successfully!")
        return redirect("laundry:expense_field_list")
    return render(request, "expenses/delete_expense_field.html", {"field": field})


# views.py - Update expense_form view
@login_required
def expense_form(request):
    user_shops = get_user_shops(request)

    if request.method == "POST":
        form = ExpenseRecordForm(request.POST)

        if form.is_valid():
            expense_record = form.save(commit=False)

            # Auto-assign shop based on user type
            if request.user.is_superuser:
                # For superuser, check if shop is provided in form data
                shop = request.POST.get('shop')
                if shop:
                    expense_record.shop = shop
                else:
                    # If no shop provided, use the first available shop or show error
                    if user_shops and len(user_shops) == 1:
                        expense_record.shop = user_shops[0]
                    else:
                        messages.error(request, "Please select a shop for this expense.")
                        context = {
                            "form": form,
                            "user_shop": user_shops[0] if user_shops else '',
                            "is_superuser": request.user.is_superuser,
                        }
                        return render(request, "expenses/expense_form.html", context)
            else:
                # Staff user - auto-assign their shop
                if user_shops and len(user_shops) == 1:
                    expense_record.shop = user_shops[0]
                else:
                    messages.error(request, "Unable to determine your shop assignment.")
                    return redirect("laundry:expense_list")

            expense_record.save()
            messages.success(request, "Expense recorded successfully!")
            return redirect("laundry:expense_list")
    else:
        form = ExpenseRecordForm()

    context = {
        "form": form,
        "user_shop": user_shops[0] if user_shops else '',
        "is_superuser": request.user.is_superuser,
    }
    return render(request, "expenses/expense_form.html", context)

@login_required
def expense_list(request):
    # Get date filters from request
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    
    # Default to current month if no dates provided
    today = timezone.now().date()
    
    try:
        if start_date_str:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        else:
            start_date = today.replace(day=1)  # First day of current month
    except (ValueError, TypeError):
        start_date = today.replace(day=1)
    
    try:
        if end_date_str:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        else:
            end_date = today  # Today as default end date
    except (ValueError, TypeError):
        end_date = today
    
    # Ensure start_date is before or equal to end_date
    if start_date > end_date:
        start_date, end_date = end_date, start_date
    
    # Filter records by date range
    records = ExpenseRecord.objects.filter(
        date__gte=start_date,
        date__lte=end_date
    ).select_related("field").order_by("-date")

    # Calculate stats for the cards
    total_amount = records.aggregate(Sum('amount'))['amount__sum'] or 0
    record_count = records.count()
    average_expense = records.aggregate(Avg('amount'))['amount__avg'] or 0

    # Build date range description
    if start_date == end_date:
        date_range_description = f"for {start_date.strftime('%B %d, %Y')}"
    else:
        date_range_description = f"from {start_date.strftime('%B %d, %Y')} to {end_date.strftime('%B %d, %Y')}"

    context = {
        "records": records,
        "total_amount": total_amount,
        "record_count": record_count,
        "average_expense": round(average_expense, 2),
        "start_date": start_date,
        "end_date": end_date,
        "date_range_description": date_range_description,
    }
    return render(request, "expenses/expense_list.html", context)

@login_required
def edit_expense_record(request, record_id):
    record = get_object_or_404(ExpenseRecord, id=record_id)
    if request.method == "POST":
        form = ExpenseRecordForm(request.POST, instance=record)
        if form.is_valid():
            form.save()
            messages.success(request, "Expense record updated successfully!")
            return redirect("laundry:expense_list")
    else:
        form = ExpenseRecordForm(instance=record)
    return render(request, "expenses/edit_expense_record.html", {"form": form, "record": record})


@login_required
def delete_expense_record(request, record_id):
    record = get_object_or_404(ExpenseRecord, id=record_id)
    if request.method == "POST":
        record.delete()
        messages.success(request, "Expense record deleted successfully!")
        return redirect("laundry:expense_list")
    return render(request, "expenses/delete_expense_record.html", {"record": record})

