from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django_daraja.mpesa.core import MpesaClient
import json
import logging
import datetime
from functools import wraps
from datetime import datetime, date, timedelta

# Django imports
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.db.models import Q, Sum
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db import IntegrityError
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth import update_session_auth_hash
from django.utils import timezone
import pytz
from django.db import transaction

from ..forms import ProfileEditForm, User, UserCreateForm, UserEditForm
from ..models import Customer, Order
from ..views import admin_required


@login_required
@admin_required
def user_add(request):
    """Create a new user without shop assignment"""
    if request.method == 'POST':
        form = UserCreateForm(request.POST)
        profile_form = ProfileEditForm(request.POST)

        if form.is_valid() and profile_form.is_valid():
            try:
                with transaction.atomic():
                    # Create base user object but don't save yet
                    user = form.save(commit=False)

                    # Get profile data
                    user_type = profile_form.cleaned_data['user_type']

                    # ✅ Assign role permissions based on user_type
                    if user_type == "admin":
                        user.is_staff = True
                        user.is_superuser = True
                    elif user_type == "staff":
                        user.is_staff = True
                        user.is_superuser = False
                    else:
                        user.is_staff = False
                        user.is_superuser = False

                    # Set user_type from profile form
                    user.user_type = user_type
                    user.save()

                messages.success(request, f"User {user.email} created successfully!")
                return redirect('laundry:user_management')

            except IntegrityError:
                error_msg = f"The email '{form.cleaned_data.get('email', '')}' is already registered. Please use a different email address."
                messages.error(request, error_msg)
                # Keep the form data so user doesn't have to re-enter everything
                return render(request, "user/user_form.html", {
                    "form": form,
                    "profile_form": profile_form,
                    "title": "Add New User"
                })
            except Exception as e:
                messages.error(request, f"Error creating user: {str(e)}")
        else:
            # Collect all form errors
            all_errors = []
            if form.errors:
                all_errors.extend([f"{field}: {error}" for field, errors in form.errors.items() for error in errors])
            if profile_form.errors:
                all_errors.extend([f"Profile {field}: {error}" for field, errors in profile_form.errors.items() for error in errors])
            
            # Show all errors
            for error in all_errors:
                messages.error(request, error)

    else:
        form = UserCreateForm()
        profile_form = ProfileEditForm()

    return render(request, "user/user_form.html", {
        "form": form,
        "profile_form": profile_form,
        "title": "Add New User"
    })


@login_required
@admin_required
def user_edit(request, pk):
    """Edit user information including profile"""
    user = get_object_or_404(User, pk=pk)

    if request.method == 'POST':
        user_form = UserEditForm(request.POST, instance=user, prefix='user')
        password_form = PasswordChangeForm(user, request.POST, prefix='password')

        # Save user information
        if 'update_user' in request.POST and user_form.is_valid():
            try:
                with transaction.atomic():
                    user = user_form.save(commit=False)

                    # Handle staff/admin permissions based on user_type
                    if user.user_type == 'admin':
                        user.is_staff = True
                        user.is_superuser = True
                    elif user.user_type == 'staff':
                        user.is_staff = True
                        user.is_superuser = False
                    else:
                        user.is_staff = False
                        user.is_superuser = False

                    user.save()

                messages.success(request, f'User {user.email} updated successfully!')
                return redirect('laundry:user_management')

            except Exception as e:
                messages.error(request, f'Error updating user: {str(e)}')

        # Change password
        elif 'change_password' in request.POST and password_form.is_valid():
            password_form.save()
            if request.user == user:
                update_session_auth_hash(request, user)
            messages.success(request, 'Password updated successfully!')
            return redirect('laundry:user_edit', pk=user.pk)

    else:
        user_form = UserEditForm(instance=user, prefix='user')
        password_form = PasswordChangeForm(user, prefix='password')

    context = {
        'user_form': user_form,
        'password_form': password_form,
        'user': user,
        'title': f'Edit User - {user.email}'
    }

    return render(request, 'user/user_edit_form.html', context)


@login_required
@admin_required
def user_profile(request, pk):
    """View user profile and details"""
    user = get_object_or_404(User, pk=pk)
    
    # Get customers created by this user
    customers_created = Customer.objects.filter(created_by=user).count()
    
    # Get orders for customers created by this user
    customers = Customer.objects.filter(created_by=user)
    user_orders = Order.objects.filter(customer__in=customers)
    
    total_orders = user_orders.count()
    total_revenue = user_orders.aggregate(total=Sum('total_price'))['total'] or 0
    
    context = {
        'user': user,
        'total_orders': total_orders,
        'total_revenue': total_revenue,
        'customers_created': customers_created,
    }
    
    return render(request, 'user/user_profile.html', context)


@login_required
@admin_required
def user_management(request):
    """User management page for admins with local time support"""

    # Start with all users
    users = User.objects.all()

    # --- Filters ---
    search_query = request.GET.get("search", "").strip()
    status_filter = request.GET.get("status", "").strip()
    user_type_filter = request.GET.get("user_type", "").strip()

    if search_query:
        users = users.filter(
            Q(email__icontains=search_query)
            | Q(first_name__icontains=search_query)
            | Q(last_name__icontains=search_query)
        )

    if status_filter:
        status_map = {
            "active": {"is_active": True},
            "inactive": {"is_active": False},
            "staff": {"is_staff": True},
            "superuser": {"is_superuser": True},
        }
        if status_filter in status_map:
            users = users.filter(**status_map[status_filter])

    if user_type_filter:
        users = users.filter(user_type=user_type_filter)

    # --- Timezone Setup ---
    local_tz = pytz.timezone("Africa/Nairobi")

    # --- Prepare Filter Options ---
    status_options = [
        {"value": "", "label": "All Status", "selected": status_filter == ""},
        {"value": "active", "label": "Active", "selected": status_filter == "active"},
        {"value": "inactive", "label": "Inactive", "selected": status_filter == "inactive"},
        {"value": "staff", "label": "Staff Users", "selected": status_filter == "staff"},
        {"value": "superuser", "label": "Superusers", "selected": status_filter == "superuser"},
    ]

    user_type_options = [
        {"value": "", "label": "All Types", "selected": user_type_filter == ""},
        {"value": "admin", "label": "Admins", "selected": user_type_filter == "admin"},
        {"value": "staff", "label": "Staff", "selected": user_type_filter == "staff"},
    ]

    # --- Prepare User Details ---
    users_with_status = []
    for user in users:
        # Determine account status
        if not user.is_active:
            status = ("inactive", "danger", "Inactive")
        elif user.is_superuser:
            status = ("superuser", "primary", "Superuser")
        elif user.is_staff:
            status = ("staff", "info", "Staff")
        else:
            status = ("active", "success", "Active")

        # Convert last login to local timezone
        if user.last_login:
            local_login_time = user.last_login.astimezone(local_tz)
            last_login_display = local_login_time.strftime("%Y-%m-%d %I:%M %p")
            days_since_login = (timezone.now() - user.last_login).days
        else:
            last_login_display = "Never"
            days_since_login = None

        # Append to list
        users_with_status.append(
            {
                "id": user.id,
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "is_active": user.is_active,
                "is_staff": user.is_staff,
                "is_superuser": user.is_superuser,
                "status": status[0],
                "status_class": status[1],
                "status_text": status[2],
                "last_login": last_login_display,
                "days_since_login": days_since_login,
                "user_type": getattr(user, "user_type", ""),
                "is_online": bool(
                    user.last_login
                    and (timezone.now() - user.last_login).seconds < 300
                ),
                "date_joined": user.date_joined.astimezone(local_tz).strftime("%Y-%m-%d %I:%M %p"),
            }
        )

    # --- Pagination ---
    paginator = Paginator(users_with_status, 20)
    page_number = request.GET.get("page")
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    # --- Statistics ---
    total_users = users.count()
    active_users = users.filter(is_active=True).count()
    inactive_users = users.filter(is_active=False).count()
    staff_users = users.filter(is_staff=True, is_superuser=False).count()
    superusers = users.filter(is_superuser=True).count()
    never_logged_in = users.filter(last_login__isnull=True).count()
    recently_active = users.filter(
        last_login__gte=timezone.now() - timezone.timedelta(days=7)
    ).count()

    # --- Context ---
    context = {
        "users": page_obj,
        "search_query": search_query,
        "status_options": status_options,
        "user_type_options": user_type_options,
        "total_users": total_users,
        "active_users": active_users,
        "inactive_users": inactive_users,
        "staff_users": staff_users,
        "superusers": superusers,
        "never_logged_in": never_logged_in,
        "recently_active": recently_active,
        "current_filters": {
            "status": status_filter,
            "user_type": user_type_filter,
        },
    }

    return render(request, "user/user_management.html", context)


@login_required
@admin_required
def user_delete(request, pk):
    """Delete a user"""
    user = get_object_or_404(User, pk=pk)
    
    # Prevent users from deleting themselves
    if user == request.user:
        messages.error(request, "You cannot delete your own account!")
        return redirect('laundry:user_management')
    
    if request.method == 'POST':
        email = user.email
        user.delete()
        messages.success(request, f'User {email} deleted successfully!')
        return redirect('laundry:user_management')
    
    context = {
        'user': user,
    }
    
    return render(request, 'user/user_confirm_delete.html', context)