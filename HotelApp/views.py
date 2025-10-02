import logging
from datetime import datetime, timedelta

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db import IntegrityError, transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

import logging
from django.utils.dateparse import parse_date

from .models import FoodCategory, FoodItem, HotelOrder as Order, HotelOrderItem
from .forms import (
    FoodCategoryForm, FoodItemForm, FoodItemAvailabilityForm,
    OrderForm, HotelOrderItemForm, BulkOrderForm
)
from .Vews.resource import HotelOrderResource

logger = logging.getLogger(__name__)


# Food Category Views
@login_required
def category_list(request):
    """Display all food categories"""
    try:
        categories = FoodCategory.objects.all()
        return render(request, 'food/category_list.html', {'categories': categories})
    except Exception as e:
        logger.error(f"Error loading category list: {str(e)}")
        messages.error(request, 'Error loading categories. Please try again.')
        return render(request, 'food/category_list.html', {'categories': []})


@login_required
def category_create(request):
    """Create a new food category"""
    try:
        if request.method == 'POST':
            form = FoodCategoryForm(request.POST)
            if form.is_valid():
                form.save()
                messages.success(request, 'Category created successfully!')
                return redirect('hotel:category_list')
        else:
            form = FoodCategoryForm()
        
        return render(request, 'food/category_form.html', {'form': form, 'title': 'Create Category'})
    
    except Exception as e:
        logger.error(f"Error creating category: {str(e)}")
        messages.error(request, 'Error creating category. Please try again.')
        return redirect('hotel:category_list')


@login_required
def category_edit(request, pk):
    """Edit an existing food category"""
    try:
        category = get_object_or_404(FoodCategory, pk=pk)
        
        if request.method == 'POST':
            form = FoodCategoryForm(request.POST, instance=category)
            if form.is_valid():
                form.save()
                messages.success(request, 'Category updated successfully!')
                return redirect('hotel:category_list')
        else:
            form = FoodCategoryForm(instance=category)
        
        return render(request, 'food/category_form.html', {'form': form, 'title': 'Edit Category'})
    
    except Exception as e:
        logger.error(f"Error editing category {pk}: {str(e)}")
        messages.error(request, 'Error updating category. Please try again.')
        return redirect('hotel:category_list')


@login_required
def category_delete(request, pk):
    """Delete a food category"""
    try:
        category = get_object_or_404(FoodCategory, pk=pk)
        
        if request.method == 'POST':
            category_name = category.name
            category.delete()
            messages.success(request, f'Category "{category_name}" deleted successfully!')
            return redirect('hotel:category_list')
        
        return render(request, 'food/category_confirm_delete.html', {'category': category})
    
    except Exception as e:
        logger.error(f"Error deleting category {pk}: {str(e)}")
        messages.error(request, 'Error deleting category. Please try again.')
        return redirect('hotel:category_list')


# Food Item Views
@login_required
def food_item_list(request):
    """Display all food items"""
    try:
        items = FoodItem.objects.all().select_related('category', 'created_by')
        return render(request, 'food/food_item_list.html', {'items': items})
    except Exception as e:
        logger.error(f"Error loading food items: {str(e)}")
        messages.error(request, 'Error loading food items. Please try again.')
        return render(request, 'food/food_item_list.html', {'items': []})


@login_required
def load_default_food_items(request):
    """Load default food items based on categories"""
    try:
        with transaction.atomic():
            # Get or create categories
            fast_food_category, _ = FoodCategory.objects.get_or_create(name="Fast Food")
            main_meals_category, _ = FoodCategory.objects.get_or_create(name="Main Meals")
            drinks_category, _ = FoodCategory.objects.get_or_create(name="Drinks & Refreshments")
            
            # Default food items with their categories
            default_food_items = [
                # Fast Food items
                {"name": "Chips", "category": fast_food_category},
                {"name": "Bhajia", "category": fast_food_category},
                {"name": "Sausages", "category": fast_food_category},
                {"name": "Smokies", "category": fast_food_category},
                {"name": "Kebab", "category": fast_food_category},
                {"name": "Samosas", "category": fast_food_category},
                {"name": "Chapo", "category": fast_food_category},
                
                # Main Meals items
                {"name": "Chicken", "category": main_meals_category},
                {"name": "Pilau", "category": main_meals_category},
                
                # Drinks & Refreshments items
                {"name": "Sodas", "category": drinks_category},
                {"name": "Ice pop", "category": drinks_category},
            ]
            
            # Create food items if they don't exist
            created_count = 0
            for item_data in default_food_items:
                food_item, created = FoodItem.objects.get_or_create(
                    name=item_data["name"],
                    defaults={
                        'category': item_data["category"],
                        'created_by': request.user,
                        'is_available': True
                    }
                )
                if created:
                    created_count += 1
            
            messages.success(request, f'Successfully loaded {created_count} default food items!')
            return redirect('hotel:food_item_list')
            
    except IntegrityError as e:
        logger.error(f"Integrity error loading default food items: {str(e)}")
        messages.error(request, 'Database error while loading default food items.')
    except Exception as e:
        logger.error(f"Error loading default food items: {str(e)}")
        messages.error(request, 'Error loading default food items. Please try again.')
    
    return redirect('hotel:food_item_list')


@login_required
def food_item_create(request):
    """Create a new food item"""
    try:
        if request.method == 'POST':
            form = FoodItemForm(request.POST, request.FILES)
            if form.is_valid():
                with transaction.atomic():
                    food_item = form.save(commit=False)
                    food_item.created_by = request.user
                    food_item.save()
                    
                    messages.success(request, 'Food item created successfully!')
                    return redirect('hotel:food_item_list')
        else:
            form = FoodItemForm()
        
        return render(request, 'food/food_item_form.html', {
            'form': form, 
            'title': 'Create Food Item'
        })
    
    except IntegrityError:
        logger.error("Integrity error when creating food item")
        messages.error(request, 'There was an error saving the food item. Please try again.')
        return redirect('hotel:food_item_list')
    except Exception as e:
        logger.error(f"Error creating food item: {str(e)}")
        messages.error(request, 'Error creating food item. Please try again.')
        return redirect('hotel:food_item_list')


@login_required
def food_item_edit(request, pk):
    """Edit an existing food item"""
    try:
        food_item = get_object_or_404(FoodItem, pk=pk)
        
        # Check if user has permission to edit
        if food_item.created_by != request.user and not request.user.is_staff and not request.user.is_superuser:
            messages.error(request, 'You do not have permission to edit this food item.')
            return redirect('hotel:food_item_list')
        
        if request.method == 'POST':
            form = FoodItemForm(request.POST, request.FILES, instance=food_item)
            if form.is_valid():
                form.save()
                messages.success(request, 'Food item updated successfully!')
                return redirect('hotel:food_item_list')
        else:
            form = FoodItemForm(instance=food_item)
        
        return render(request, 'food/food_item_form.html', {
            'form': form, 
            'title': 'Edit Food Item'
        })
    
    except Exception as e:
        logger.error(f"Error editing food item {pk}: {str(e)}")
        messages.error(request, 'Error updating food item. Please try again.')
        return redirect('hotel:food_item_list')


@login_required
def food_item_availability(request, pk):
    """Update food item availability"""
    try:
        food_item = get_object_or_404(FoodItem, pk=pk)
        
        # Check if user has permission to update availability
        if food_item.created_by != request.user and not request.user.is_staff and not request.user.is_superuser:
            messages.error(request, 'You do not have permission to update availability for this food item.')
            return redirect('hotel:food_item_list')
        
        if request.method == 'POST':
            form = FoodItemAvailabilityForm(request.POST, instance=food_item)
            if form.is_valid():
                form.save()
                messages.success(request, 'Availability updated successfully!')
                return redirect('hotel:food_item_list')
        else:
            form = FoodItemAvailabilityForm(instance=food_item)
        
        return render(request, 'food/food_item_availability.html', {
            'form': form, 
            'food_item': food_item
        })
    
    except Exception as e:
        logger.error(f"Error updating availability for food item {pk}: {str(e)}")
        messages.error(request, 'Error updating availability. Please try again.')
        return redirect('hotel:food_item_list')


@login_required
def food_item_delete(request, pk):
    """Delete a food item"""
    try:
        food_item = get_object_or_404(FoodItem, pk=pk)
        
        # Check if user has permission to delete
        if food_item.created_by != request.user and not request.user.is_staff and not request.user.is_superuser:
            messages.error(request, 'You do not have permission to delete this food item.')
            return redirect('hotel:food_item_list')
        
        if request.method == 'POST':
            food_item_name = food_item.name
            food_item.delete()
            messages.success(request, f'Food item "{food_item_name}" deleted successfully!')
            return redirect('hotel:food_item_list')
        
        return render(request, 'food/food_item_confirm_delete.html', {'food_item': food_item})
    
    except Exception as e:
        logger.error(f"Error deleting food item {pk}: {str(e)}")
        messages.error(request, 'Error deleting food item. Please try again.')
        return redirect('hotel:food_item_list')


# Order Views
@login_required
def create_order(request):
    """Create a new order - only shows available food items"""
    try:
        # Create a custom formset that includes price field
        class HotelOrderItemFormWithPrice(HotelOrderItemForm):
            price = forms.DecimalField(
                max_digits=10, 
                decimal_places=2,
                required=True,
                label="Price per item",
                help_text="Enter the price for this food item"
            )
            
            class Meta(HotelOrderItemForm.Meta):
                fields = ['food_item', 'quantity', 'price']
            
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                # Only show available food items in the dropdown
                self.fields['food_item'].queryset = FoodItem.objects.filter(
                    is_available=True,
                    quantity__gt=0  # Only items with stock available
                ).select_related('category').order_by('category__name', 'name')
                
                # Add CSS classes for better styling
                self.fields['food_item'].widget.attrs.update({
                    'class': 'food-item-select w-full p-3 border border-gray-300 rounded-lg'
                })
                self.fields['quantity'].widget.attrs.update({
                    'class': 'quantity-input w-full p-3 border border-gray-300 rounded-lg',
                    'min': '1',
                    'value': '1'
                })
                self.fields['price'].widget.attrs.update({
                    'class': 'price-input w-full p-3 border border-gray-300 rounded-lg',
                    'step': '0.01',
                    'min': '0',
                    'placeholder': '0.00'
                })

        HotelOrderItemFormSet = forms.inlineformset_factory(
            Order,
            HotelOrderItem,
            form=HotelOrderItemFormWithPrice,
            extra=1,
            can_delete=False,
            fields=['food_item', 'quantity', 'price']
        )

        if request.method == 'POST':
            order = Order()
            order_form = OrderForm(request.POST, instance=order)
            item_formset = HotelOrderItemFormSet(request.POST, instance=order, prefix="items")

            if order_form.is_valid() and item_formset.is_valid():
                with transaction.atomic():
                    order = order_form.save(commit=False)
                    order.created_by = request.user
                    order.save()

                    instances = item_formset.save(commit=False)

                    # Stock check (double validation for safety)
                    stock_errors = []
                    for instance in instances:
                        if instance.food_item:
                            available_qty = instance.food_item.quantity
                            if instance.quantity > available_qty:
                                stock_errors.append(
                                    f"Only {available_qty} portions of {instance.food_item.name} are available. You requested {instance.quantity}."
                                )
                            # Also check if item is still available
                            elif not instance.food_item.is_available:
                                stock_errors.append(
                                    f"{instance.food_item.name} is no longer available."
                                )

                    if stock_errors:
                        for error in stock_errors:
                            messages.error(request, error)
                        return render(request, 'food/create_order.html', {
                            'order_form': order_form,
                            'item_formset': item_formset,
                            'available_food_items': FoodItem.objects.filter(is_available=True, quantity__gt=0)
                        })
                    
                    # Save valid items and update stock
                    for instance in instances:
                        if instance.food_item:  # Additional safety check
                            instance.order = order
                            instance.save()
                            
                            # Update stock
                            instance.food_item.quantity -= instance.quantity
                            if instance.food_item.quantity <= 0:
                                instance.food_item.is_available = False
                            instance.food_item.save()

                    messages.success(request, 'Order placed successfully!')
                    return redirect('hotel:order_list')
            else:
                messages.error(request, 'Please correct the errors below.')
        else:
            order_form = OrderForm()
            item_formset = HotelOrderItemFormSet(queryset=HotelOrderItem.objects.none(), prefix="items")

        # Get available food items for the template (for JavaScript or display)
        available_food_items = FoodItem.objects.filter(
            is_available=True, 
            quantity__gt=0
        ).select_related('category').order_by('category__name', 'name')

        return render(request, 'food/create_order.html', {
            'order_form': order_form,
            'item_formset': item_formset,
            'available_food_items': available_food_items,
        })
    
    except Exception as e:
        logger.error(f"Error creating order: {str(e)}")
        messages.error(request, 'Error creating order. Please try again.')
        return redirect('hotel:order_list')


logger = logging.getLogger(__name__)


def get_date_filters(request):
    """Helper function to extract and validate date filters from request"""
    start_date_str = request.GET.get('start_date') or request.POST.get('start_date')
    end_date_str = request.GET.get('end_date') or request.POST.get('end_date')
    
    # Default to current month if no dates provided
    today = timezone.now().date()
    
    try:
        if start_date_str:
            start_date = parse_date(start_date_str)
            if not start_date:
                raise ValueError("Invalid start date format")
        else:
            start_date = today.replace(day=1)  # First day of current month
    except (ValueError, TypeError) as e:
        logger.warning(f"Invalid start date: {start_date_str}, using default. Error: {str(e)}")
        start_date = today.replace(day=1)
    
    try:
        if end_date_str:
            end_date = parse_date(end_date_str)
            if not end_date:
                raise ValueError("Invalid end date format")
        else:
            end_date = today  # Today as default end date
    except (ValueError, TypeError) as e:
        logger.warning(f"Invalid end date: {end_date_str}, using default. Error: {str(e)}")
        end_date = today
    
    # Ensure start_date is before or equal to end_date
    if start_date > end_date:
        messages.warning(request, 'Start date cannot be after end date. Dates have been swapped.')
        start_date, end_date = end_date, start_date
    
    return start_date, end_date


@login_required
def order_list(request):
    """Display orders with comprehensive date filtering, pagination, and export functionality"""
    try:
        # Get date filters
        start_date, end_date = get_date_filters(request)
        export = request.GET.get('export')
        export_format = request.GET.get('format', 'csv')
        
        # Build filter description for messages
        date_filter_description = ""
        if start_date and end_date:
            if start_date == end_date:
                date_filter_description = f"for {start_date.strftime('%B %d, %Y')}"
            else:
                date_filter_description = f"from {start_date.strftime('%B %d, %Y')} to {end_date.strftime('%B %d, %Y')}"
        
        # Filter orders by date range
        orders = Order.objects.filter(
            created_at__date__gte=start_date,
            created_at__date__lte=end_date
        ).prefetch_related('order_items__food_item').select_related('created_by').order_by('-created_at')
        
        # Handle export functionality
        if export:
            try:
                dataset = HotelOrderResource().export(orders)
                
                if export_format == 'xlsx':
                    response = HttpResponse(
                        dataset.xlsx, 
                        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                    )
                    filename = f"orders_{start_date}_{end_date}.xlsx"
                elif export_format == 'json':
                    response = HttpResponse(dataset.json, content_type='application/json')
                    filename = f"orders_{start_date}_{end_date}.json"
                else:  # Default to CSV
                    response = HttpResponse(dataset.csv, content_type='text/csv')
                    filename = f"orders_{start_date}_{end_date}.csv"
                
                response['Content-Disposition'] = f'attachment; filename="{filename}"'
                messages.success(request, f'Orders exported successfully {date_filter_description}!')
                return response
            
            except Exception as e:
                logger.error(f"Error exporting orders: {str(e)}")
                messages.error(request, 'Error exporting orders. Please try again.')
                return redirect('hotel:order_list')
        
        # Calculate totals and summary statistics
        total_orders = orders.count()
        total_revenue = 0
        order_list_with_totals = []
        
        for order in orders:
            order_total = 0
            for item in order.order_items.all():
                item_total = item.quantity * item.price
                order_total += item_total
            order.total_amount = order_total
            total_revenue += order_total
            order_list_with_totals.append(order)
        
        # Calculate average order value
        average_order_value = total_revenue / total_orders if total_orders > 0 else 0
        
        # Prepare summary data
        summary = {
            'total_orders': total_orders,
            'total_revenue': total_revenue,
            'average_order_value': average_order_value,
            'date_range_description': date_filter_description,
        }
        
        # Pagination with error handling
        paginator = Paginator(order_list_with_totals, 20)
        page_number = request.GET.get('page', 1)
        
        try:
            page_obj = paginator.page(page_number)
        except PageNotAnInteger:
            page_obj = paginator.page(1)
        except EmptyPage:
            page_obj = paginator.page(paginator.num_pages)
        
        # Calculate pagination indices
        page_obj.start_index = (page_obj.number - 1) * paginator.per_page + 1
        page_obj.end_index = min(page_obj.number * paginator.per_page, paginator.count)
        
        # Add success message for filtered results
        if total_orders > 0 and date_filter_description:
            messages.info(request, f'Showing {total_orders} orders {date_filter_description}.')
        
        return render(request, 'food/order_list.html', {
            'orders': page_obj,
            'summary': summary,
            'start_date': start_date,
            'end_date': end_date,
            'date_filter_description': date_filter_description,
        })
    
    except Exception as e:
        logger.error(f"Error loading order list: {str(e)}")
        messages.error(request, 'Error loading orders. Please try again.')
        return render(request, 'food/order_list.html', {
            'orders': [],
            'summary': {
                'total_orders': 0, 
                'total_revenue': 0, 
                'average_order_value': 0,
                'date_range_description': ''
            },
            'start_date': timezone.now().replace(day=1).date(),
            'end_date': timezone.now().date(),
        })


@login_required
def export_orders(request):
    """Dedicated export view with date filtering"""
    try:
        if request.method == 'POST':
            # Get date filters from POST data
            start_date, end_date = get_date_filters(request)
            export_format = request.POST.get('format', 'csv')
            
            # Filter orders by date range
            orders = Order.objects.filter(
                created_at__date__gte=start_date,
                created_at__date__lte=end_date
            ).prefetch_related('order_items__food_item').order_by('-created_at')
            
            # Create the dataset using the resource
            dataset = HotelOrderResource().export(orders)
            
            # Determine response type and filename
            if export_format == 'xlsx':
                response = HttpResponse(
                    dataset.xlsx, 
                    content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                )
                filename = f"orders_{start_date}_{end_date}.xlsx"
            elif export_format == 'json':
                response = HttpResponse(dataset.json, content_type='application/json')
                filename = f"orders_{start_date}_{end_date}.json"
            else:  # Default to CSV
                response = HttpResponse(dataset.csv, content_type='text/csv')
                filename = f"orders_{start_date}_{end_date}.csv"
            
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            
            # Add success message that will show when user returns to the page
            messages.success(request, f'Orders exported successfully for {start_date} to {end_date}!')
            return response
        
        # If not POST, redirect to order list
        return redirect('hotel:order_list')
    
    except Exception as e:
        logger.error(f"Error exporting orders: {str(e)}")
        messages.error(request, 'Error exporting orders. Please try again.')
        return redirect('hotel:order_list')

@login_required
def order_detail(request, pk):
    """Display order details"""
    try:
        order = get_object_or_404(Order, pk=pk)
        
        # Calculate order total
        total = 0
        for item in order.order_items.all():
            item.total_price = item.quantity * item.price
            total += item.total_price
        
        order.total_amount = total
        
        return render(request, 'food/order_detail.html', {'order': order})
    
    except Exception as e:
        logger.error(f"Error loading order detail {pk}: {str(e)}")
        messages.error(request, 'Error loading order details. Please try again.')
        return redirect('hotel:order_list')


@login_required
def order_edit(request, pk):
    """Edit an existing order"""
    try:
        order = get_object_or_404(Order, pk=pk)
        
        OrderItemFormSet = forms.inlineformset_factory(
            Order,
            HotelOrderItem, 
            form=HotelOrderItemForm, 
            extra=1, 
            can_delete=True,
            fields=['food_item', 'quantity', 'price']
        )
        
        if request.method == 'POST':
            formset = OrderItemFormSet(request.POST, instance=order, prefix="order_items")
            
            if formset.is_valid():
                with transaction.atomic():
                    instances = formset.save(commit=False)
                    
                    # Handle deleted items - restore stock
                    for obj in formset.deleted_objects:
                        if obj.food_item:
                            obj.food_item.quantity += obj.quantity
                            obj.food_item.is_available = True
                            obj.food_item.save()
                        obj.delete()
                    
                    # Handle stock management for changed items
                    for form in formset:
                        if form.has_changed() and form.instance.pk:  # Existing item changed
                            order_item = form.instance
                            original_item = HotelOrderItem.objects.get(pk=order_item.pk)
                            
                            # Handle quantity changes
                            if 'quantity' in form.changed_data and order_item.food_item:
                                original_qty = original_item.quantity
                                quantity_diff = order_item.quantity - original_qty
                                
                                if quantity_diff != 0:
                                    if quantity_diff > 0:
                                        if order_item.food_item.quantity >= quantity_diff:
                                            order_item.food_item.sell(quantity_diff)
                                        else:
                                            messages.error(request, f"Not enough stock for {order_item.food_item.name}")
                                            return redirect('hotel:order_edit', pk=order.pk)
                                    else:
                                        order_item.food_item.quantity += abs(quantity_diff)
                                        order_item.food_item.is_available = True
                                        order_item.food_item.save()
                            
                            # Handle food item changes
                            if 'food_item' in form.changed_data:
                                if original_item.food_item:
                                    original_item.food_item.quantity += original_item.quantity
                                    original_item.food_item.is_available = True
                                    original_item.food_item.save()
                                
                                if order_item.food_item and order_item.food_item.quantity >= order_item.quantity:
                                    order_item.food_item.sell(order_item.quantity)
                                else:
                                    messages.error(request, f"Not enough stock for {order_item.food_item.name}")
                                    return redirect('hotel:order_edit', pk=order.pk)
                        
                        elif not form.instance.pk and form.cleaned_data.get('food_item'):  # New item
                            order_item = form.instance
                            if order_item.quantity > 0:
                                if order_item.food_item.quantity >= order_item.quantity:
                                    order_item.food_item.sell(order_item.quantity)
                                else:
                                    messages.error(request, f"Not enough stock for {order_item.food_item.name}")
                                    return redirect('hotel:order_edit', pk=order.pk)
                    
                    # Save all valid instances
                    for instance in instances:
                        instance.save()
                    
                    messages.success(request, f'Order #{order.id} updated successfully!')
                    return redirect('hotel:order_detail', pk=order.pk)
            else:
                logger.warning(f"Formset errors for order {pk}: {formset.errors}")
                messages.error(request, 'Please correct the errors below.')
        
        else:
            formset = OrderItemFormSet(instance=order, prefix="order_items")
        
        available_food_items = FoodItem.objects.filter(is_available=True).select_related('category')
        
        return render(request, 'food/order_edit.html', {
            'formset': formset,
            'order': order,
            'available_food_items': available_food_items,
            'title': f'Edit Order #{order.id}'
        })
    
    except Exception as e:
        logger.error(f"Error editing order {pk}: {str(e)}")
        messages.error(request, 'Error updating order. Please try again.')
        return redirect('hotel:order_list')


@login_required
def order_delete(request, pk):
    """Delete an order"""
    try:
        order = get_object_or_404(Order, pk=pk)
        
        if request.method == 'POST':
            order_id = order.id
            order.delete()
            messages.success(request, f'Order #{order_id} has been deleted successfully.')
            return redirect('hotel:order_list')
        
        return render(request, 'food/order_confirm_delete.html', {'order': order})
    
    except Exception as e:
        logger.error(f"Error deleting order {pk}: {str(e)}")
        messages.error(request, 'Error deleting order. Please try again.')
        return redirect('hotel:order_list')


# API Views
@login_required
def get_food_item_info(request, pk):
    """AJAX endpoint to get food item information"""
    try:
        if not request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'message': 'Invalid request'})
        
        food_item = get_object_or_404(FoodItem, pk=pk, is_available=True)
        
        return JsonResponse({
            'success': True,
            'name': food_item.name,
            'quantity': food_item.quantity,
            'description': food_item.description or '',
        })
    
    except Exception as e:
        logger.error(f"Error getting food item info {pk}: {str(e)}")
        return JsonResponse({'success': False, 'message': 'Error retrieving food item information'})


@login_required
def order_update_ajax(request, pk):
    """AJAX endpoint for updating order status"""
    try:
        if request.method == 'POST' and request.headers.get('x-requested-with') == 'XMLHttpRequest':
            order = get_object_or_404(Order, pk=pk)
            new_status = request.POST.get('order_status')
            
            # Validate status (you might want to define STATUS_CHOICES in your model)
            valid_statuses = ['Pending', 'In Progress', 'Served', 'Cancelled']  # Adjust as needed
            if new_status in valid_statuses:
                order.order_status = new_status
                order.save()
                
                return JsonResponse({
                    'success': True,
                    'message': f'Order status updated to {new_status}',
                    'new_status': new_status,
                    'status_display': new_status  # You might want to add get_status_display method
                })
            
            return JsonResponse({'success': False, 'message': 'Invalid status'})
        
        return JsonResponse({'success': False, 'message': 'Invalid request'})
    
    except Exception as e:
        logger.error(f"Error updating order status {pk}: {str(e)}")
        return JsonResponse({'success': False, 'message': 'Error updating order status'})