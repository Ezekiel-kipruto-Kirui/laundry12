from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count, Q
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger

from ..models import Customer
from ..forms import CustomerForm
from ..views import (
    apply_order_permissions,
    check_customer_permission,
    get_user_shops,
    apply_customer_permissions,
    User,
    shop_required,
)


@login_required
@shop_required
def search_customers(request):
    """API endpoint to search for customers by phone or name"""
    if request.method == 'GET':
        query = request.GET.get('q', '').strip()

        if len(query) < 2:
            return JsonResponse({'customers': []})

        customers = Customer.objects.filter(
            Q(phone__icontains=query) | Q(name__icontains=query)
        )

        customers = apply_customer_permissions(customers, request)
        customers = customers[:10]

        results = [
            {
                'id': c.id,
                'name': c.name,
                'phone': str(c.phone),
                
            }
            for c in customers
        ]

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

    # Search
    search_query = request.GET.get('search', '')
    if search_query:
        customers = customers.filter(
            Q(name__icontains=search_query) |
            Q(phone__icontains=search_query)
        )

    # # Apply permission filtering
    # customers = apply_customer_permissions(customers, request)

    # # ✅ Simplified: remove shop/laundry_profile dependency
    # # If not superuser, only show customers created by this user
    # if not request.user.is_superuser:
    #     customers = customers.filter(created_by=request.user)

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

    return render(request, 'Customer/customer_management.html', context)


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

    context = {'form': form, 'title': 'Add New Customer'}
    return render(request, 'Customer/customer_form.html', context)


@login_required
@shop_required
def customer_edit(request, pk):
    """Edit customer information"""
    customer = get_object_or_404(Customer, pk=pk)

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
        'title': f'Edit Customer - {customer.name}',
    }

    return render(request, 'Customer/customer_form.html', context)


@login_required
@shop_required
def customer_delete(request, pk):
    """Delete a customer (only if they have no orders)"""
    customer = get_object_or_404(Customer, pk=pk)

    if not check_customer_permission(request, customer):
        messages.error(request, "You don't have permission to delete this customer.")
        return redirect('laundry:customer_management')

    if request.method == 'POST':
        if customer.orders.exists():
            messages.error(request, f'Cannot delete {customer.name} because they have existing orders.')
            return redirect('laundry:customer_management')

        customer_name = customer.name
        customer.delete()
        messages.success(request, f'Customer {customer_name} deleted successfully!')
        return redirect('laundry:customer_management')

    total_orders = customer.orders.count()
    completed_orders = customer.orders.filter(order_status="Delivered_picked").count()

    context = {
        'customer': customer,
        'total_orders': total_orders,
        'completed_orders': completed_orders,
    }

    return render(request, 'Customer/customer_confirm_delete.html', context)


@login_required
@shop_required
def customer_orders(request, pk):
    """View all orders for a specific customer"""
    customer = get_object_or_404(Customer, pk=pk)

    if not check_customer_permission(request, customer):
        messages.error(request, "You don't have permission to view this customer's orders.")
        return redirect('laundry:customer_management')

    orders = customer.orders.all()
    orders = apply_order_permissions(orders, request)

    total_orders = orders.count()
    total_spent = orders.aggregate(total=Sum('total_price'))['total'] or 0
    avg_order_value = total_spent / total_orders if total_orders > 0 else 0

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

    return render(request, 'Customer/customer_orders.html', context)
