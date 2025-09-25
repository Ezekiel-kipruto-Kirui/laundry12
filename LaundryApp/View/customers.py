
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum,Count,Q
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger

from ..models import (
    Customer, 
    )
from ..forms import ( 
    CustomerForm,
    Customer, 
)

from ..views import apply_order_permissions, check_customer_permission, get_user_shops,apply_customer_permissions,User, shop_required



@login_required
@shop_required
def search_customers(request):
    """API endpoint to search for customers by phone or name"""
    if request.method == 'GET':
        query = request.GET.get('q', '').strip()
        
        if len(query) < 2:
            return JsonResponse({'customers': []})
        
        # Base queryset
        customers = Customer.objects.filter(
            Q(phone__icontains=query) | Q(name__icontains=query)
        )
        
        # Apply permission filtering
        customers = apply_customer_permissions(customers, request)
        
        # Apply the limit AFTER all filtering
        customers = customers[:10]  # Limit to 10 results
        
        results = []
        for customer in customers:
            results.append({
                'id': customer.id,
                'name': customer.name,
                'phone': str(customer.phone),  # Convert PhoneNumber to string
                'address': customer.address,
            })
        
        return JsonResponse({'customers': results})
    
    return JsonResponse({'error': 'Invalid request'}, status=400)


@login_required
@shop_required
def customer_management(request):
    """Customer management page with search and filtering"""
    customers = Customer.objects.annotate(
        order_count=Count('orders'),
        total_spent=Sum('orders__total_price')
    ).order_by('-id')
    
    # Search functionality
    search_query = request.GET.get('search', '')
    if search_query:
        customers = customers.filter(
            Q(name__icontains=search_query) |
            Q(phone__icontains=search_query)
        )
    
    # Apply permission filtering
    customers = apply_customer_permissions(customers, request)
    
    # Also include customers created by users from the same shop
    user_shops = get_user_shops(request)
    if user_shops is not None and user_shops and not request.user.is_superuser:
        # Get users from the same shops
        same_shop_user_ids = User.objects.filter(
            laundry_profile__shop__in=user_shops
        ).values_list('id', flat=True)
        
        # Include customers created by users from the same shop
        same_shop_customers = Customer.objects.filter(
            created_by_id__in=same_shop_user_ids
        )
        
        # Combine with existing customers
        customers = customers | same_shop_customers
        customers = customers.distinct()
    
    # Pagination
    paginator = Paginator(customers, 20)
    page_number = request.GET.get('page')
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)
    
    context = {
        'customers': page_obj,
        'search_query': search_query,
        'total_customers': customers.count(),
    }
    
    return render(request, 'Admin/customer_management.html', context)

@login_required
@shop_required
def customer_add(request):
    """Add new customer"""
    if request.method == 'POST':
        form = CustomerForm(request.POST)
        if form.is_valid():
            customer = form.save(commit=False)
            customer.created_by = request.user
            customer.save()
            messages.success(request, f'Customer {customer.name} added successfully!')
            return redirect('laundry:customer_management')
    else:
        form = CustomerForm()
    
    context = {
        'form': form,
        'title': 'Add New Customer'
    }
    
    return render(request, 'Admin/customer_form.html', context)

@login_required
@shop_required
def customer_edit(request, pk):
    """Edit customer information"""
    customer = get_object_or_404(Customer, pk=pk)
    
    # Check if user has permission to edit this customer
    if not check_customer_permission(request, customer):
        messages.error(request, "You don't have permission to edit this customer.")
        return redirect('laundry:customer_management')
    
    if request.method == 'POST':
        form = CustomerForm(request.POST, instance=customer)
        if form.is_valid():
            form.save()
            messages.success(request, f'Customer {customer.name} updated successfully!')
            return redirect('laundry:customer_management')
    else:
        form = CustomerForm(instance=customer)
    
    context = {
        'form': form,
        'customer': customer,
        'title': f'Edit Customer - {customer.name}'
    }
    
    return render(request, 'Admin/customer_form.html', context)

@login_required
@shop_required
def customer_delete(request, pk):
    """Delete a customer (only if they have no orders)"""
    customer = get_object_or_404(Customer, pk=pk)
    
    # Check if user has permission
    if not check_customer_permission(request, customer):
        messages.error(request, "You don't have permission to delete this customer.")
        return redirect('laundry:customer_management')
    
    if request.method == 'POST':
        # Check if customer has orders
        if customer.orders.exists():
            messages.error(request, f'Cannot delete {customer.name} because they have existing orders.')
            return redirect('laundry:customer_management')
        
        customer_name = customer.name
        customer.delete()
        messages.success(request, f'Customer {customer_name} deleted successfully!')
        return redirect('laundry:customer_management')
    
    context = {
        'customer': customer,
    }
    
    return render(request, 'Admin/customer_confirm_delete.html', context)

@login_required
@shop_required
def customer_orders(request, pk):
    """View all orders for a specific customer"""
    customer = get_object_or_404(Customer, pk=pk)
    
    # Check permission
    if not check_customer_permission(request, customer):
        messages.error(request, "You don't have permission to view this customer's orders.")
        return redirect('laundry:customer_management')
    
    # Get orders for this customer
    orders = customer.orders.all()
    
    # Apply order permissions
    orders = apply_order_permissions(orders, request)
    
    # Get statistics
    total_orders = orders.count()
    total_spent = orders.aggregate(total=Sum('total_price'))['total'] or 0
    avg_order_value = total_spent / total_orders if total_orders > 0 else 0
    
    # Pagination
    paginator = Paginator(orders, 15)
    page_number = request.GET.get('page')
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)
    
    context = {
        'customer': customer,
        'orders': page_obj,
        'total_orders': total_orders,
        'total_spent': total_spent,
        'avg_order_value': avg_order_value,
    }
    
    return render(request, 'Admin/customer_orders.html', context) 



    