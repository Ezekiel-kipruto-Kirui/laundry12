
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
import logging


# Django imports
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required

from django.db.models import Q, Prefetch, Sum, Count, Avg

from django.contrib.auth import login as auth_login, logout as auth_logout



from django.contrib.auth import get_user_model



# Local imports
from ..models import (    
    HotelExpenseRecord ,
    HotelExpenseField, 
    
  
    )
from ..forms import ( 
    ExpenseFieldForm,
    HotelExpenseRecordForm,
    
)



# Setup logger
logger = logging.getLogger(__name__)
User = get_user_model()

@login_required
def create_expense_field(request):
    if request.method == "POST":
        raw_labels = request.POST.get("labels", "").strip()

        if not raw_labels:  # Nothing entered at all
            messages.error(request, "Please enter at least one expense field.")
            return redirect("hotel:createhotel_expense_field")

        # Split by comma, clean up whitespace, remove empties
        labels = [lbl.strip() for lbl in raw_labels.split(",") if lbl.strip()]

        created_count = 0
        for label in labels:
            obj, created = HotelExpenseField.objects.get_or_create(label=label)
            if created:
                created_count += 1

        if created_count > 0:
            messages.success(request, f"Successfully created {created_count} expense field(s)!")
        else:
            messages.info(request, "All entered expense fields already exist.")

        return redirect("hotel:expense_field_list")

    return render(request, "Hotelexpenses/create_expense_field.html")


@login_required
def expense_field_list(request):
    fields = HotelExpenseField.objects.all()
    return render(request, "Hotelexpenses/expense_field_list.html", {"fields": fields})


@login_required
def edit_expense_field(request, field_id):
    field = get_object_or_404(HotelExpenseField, id=field_id)
    if request.method == "POST":
        form = ExpenseFieldForm(request.POST, instance=field)
        if form.is_valid():
            form.save()
            messages.success(request, "Expense field updated successfully!")
            return redirect("hotel:expense_field_list")
    else:
        form = ExpenseFieldForm(instance=field)
    return render(request, "Hotelexpenses/edit_expense_field.html", {"form": form, "field": field})


@login_required
def delete_expense_field(request, field_id):
    field = get_object_or_404(HotelExpenseField, id=field_id)
    if request.method == "POST":
        field.delete()
        messages.success(request, "Expense field deleted successfully!")
        return redirect("hotel:expense_field_list")
    return render(request, "Hotelexpenses/delete_expense_field.html", {"field": field})


@login_required
def expense_form(request):
    if request.method == "POST":
        form = HotelExpenseRecordForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Expense recorded successfully!")
            return redirect("hotel:expense_list")
    else:
        form = HotelExpenseRecordForm()
    return render(request, "Hotelexpenses/expense_form.html", {"form": form})


@login_required
def expense_list(request):
    records = HotelExpenseRecord.objects.select_related("field").order_by("-date")

    # Calculate stats for the cards
    total_amount = records.aggregate(Sum('amount'))['amount__sum'] or 0
    record_count = records.count()
    average_expense = records.aggregate(Avg('amount'))['amount__avg'] or 0

    context = {
        "records": records,
        "total_amount": total_amount,
        "record_count": record_count,
        "average_expense": round(average_expense, 2),
    }
    return render(request, "Hotelexpenses/expense_list.html", context)


@login_required
def edit_expense_record(request, record_id):
    record = get_object_or_404(HotelExpenseRecord, id=record_id)
    if request.method == "POST":
        form = HotelExpenseRecordForm(request.POST, instance=record)
        if form.is_valid():
            form.save()
            messages.success(request, "Expense record updated successfully!")
            return redirect("hotel:expense_list")
    else:
        form = HotelExpenseRecordForm(instance=record)
    return render(request, "Hotelexpenses/edit_expense_record.html", {"form": form, "record": record})


@login_required
def delete_expense_record(request, record_id):
    record = get_object_or_404(HotelExpenseRecord, id=record_id)
    if request.method == "POST":
        record.delete()
        messages.success(request, "Expense record deleted successfully!")
        return redirect("hotel:expense_list")
    return render(request, "Hotelexpenses/delete_expense_record.html", {"record": record})
