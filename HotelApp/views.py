import logging

from django.shortcuts import render

# Create your views here.
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.db import IntegrityError, transaction
from django.db.models import Sum
from .models import FoodCategory, FoodItem, Order, HotelOrderItem
from .forms import (
    FoodCategoryForm, FoodItemForm, FoodItemAvailabilityForm,
    OrderForm, HotelOrderItemForm, BulkOrderForm
)

logger = logging.getLogger(__name__)

# Food Category Views
@login_required
def category_list(request):
    categories = FoodCategory.objects.all()
    return render(request, 'food/category_list.html', {'categories': categories})

@login_required
def category_create(request):
    if request.method == 'POST':
        form = FoodCategoryForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Category created successfully!')
            return redirect('hotel:category_list')
    else:
        form = FoodCategoryForm()
    return render(request, 'food/category_form.html', {'form': form, 'title': 'Create Category'})

@login_required
def category_edit(request, pk):
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

@login_required
def category_delete(request, pk):
    category = get_object_or_404(FoodCategory, pk=pk)
    if request.method == 'POST':
        category.delete()
        messages.success(request, 'Category deleted successfully!')
        return redirect('hotel:category_list')
    return render(request, 'food/category_confirm_delete.html', {'category': category})

# Food Item Views
@login_required
def food_item_list(request):
    # Show all food items to all authenticated users
    items = FoodItem.objects.all()
    return render(request, 'food/food_item_list.html', {'items': items})



@login_required
def load_default_food_items(request):
    """Load default food items based on categories"""
    try:
        with transaction.atomic():
            # Get or create categories
            fast_food_category, _ = FoodCategory.objects.get_or_create(
                name="Fast Food",
            )
            
            main_meals_category, _ = FoodCategory.objects.get_or_create(
                name="Main Meals",
            )
            
            drinks_category, _ = FoodCategory.objects.get_or_create(
                name="Drinks & Refreshments",
            )
            
            # Default food items with their categories
            default_food_items = [
                # Fast Food items
                {"name": "Chips", "category": fast_food_category, "price": 0},
                {"name": "Bhajia", "category": fast_food_category, "price": 0},
                {"name": "Sausages", "category": fast_food_category, "price": 0},
                {"name": "Smokies", "category": fast_food_category, "price": 0},
                {"name": "Kebab", "category": fast_food_category, "price": 0},
                {"name": "Samosas", "category": fast_food_category, "price": 0},
                {"name": "Chapo", "category": fast_food_category, "price": 0},
                
                # Main Meals items
                {"name": "Chicken", "category": main_meals_category, "price": 0},
                {"name": "Pilau", "category": main_meals_category, "price": 0},
                
                # Drinks & Refreshments items
                {"name": "Sodas", "category": drinks_category, "price": 0},
                {"name": "Ice pop", "category": drinks_category, "price": 0},
            ]
            
            # Create food items if they don't exist
            created_count = 0
            for item_data in default_food_items:
                food_item, created = FoodItem.objects.get_or_create(
                    name=item_data["name"],
                    defaults={
                        'category': item_data["category"],
                        'price': item_data["price"],
                        'created_by': request.user,
                        'is_available': True
                    }
                )
                if created:
                    created_count += 1
            
            messages.success(request, f'Successfully loaded {created_count} default food items!')
            return redirect('hotel:food_item_list')
            
    except Exception as e:
        messages.error(request, f'Error loading default food items: {str(e)}')
        logger.error(f"Error loading default food items: {str(e)}")
        return redirect('hotel:food_item_list')

@login_required
def food_item_create(request):
    if request.method == 'POST':
        form = FoodItemForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                with transaction.atomic():
                    food_item = form.save(commit=False)
                    food_item.created_by = request.user
                    
                    # Handle image upload with validation
                    if 'image' in request.FILES:
                        image_file = request.FILES['image']
                        
                        # Basic image validation
                        if image_file.size > 5 * 1024 * 1024:  # 5MB limit
                            messages.error(request, 'Image size must be less than 5MB.')
                            return render(request, 'food/food_item_form.html', {
                                'form': form, 
                                'title': 'Create Food Item'
                            })
                        
                        # Check file type
                        allowed_types = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']
                        if image_file.content_type not in allowed_types:
                            messages.error(request, 'Please upload a valid image file (JPEG, PNG, GIF, or WEBP).')
                            return render(request, 'food/food_item_form.html', {
                                'form': form, 
                                'title': 'Create Food Item'
                            })
                        
                        food_item.image = image_file
                    
                    food_item.save()
                    messages.success(request, 'Food item created successfully!')
                    return redirect('hotel:food_item_list')
                    
            except IntegrityError:
                messages.error(request, 'There was an error saving the food item. Please try again.')
                logger.error("Integrity error when creating food item")
            except Exception as e:
                messages.error(request, f'Error creating food item: {str(e)}')
                logger.error(f"Error creating food item: {str(e)}")
                
    else:
        form = FoodItemForm()
    
    return render(request, 'food/food_item_form.html', {
        'form': form, 
        'title': 'Create Food Item'
    })

@login_required
def food_item_edit(request, pk):
    # Allow editing only if user created the item or is staff/superuser
    food_item = get_object_or_404(FoodItem, pk=pk)
    
    # Check if user has permission to edit (creator, staff, or superuser)
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
    return render(request, 'food/food_item_form.html', {'form': form, 'title': 'Edit Food Item'})

@login_required
def food_item_availability(request, pk):
    # Allow availability update only if user created the item or is staff/superuser
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
    return render(request, 'food/food_item_availability.html', {'form': form, 'food_item': food_item})

@login_required
def food_item_delete(request, pk):
    # Allow deletion only if user created the item or is staff/superuser
    food_item = get_object_or_404(FoodItem, pk=pk)
    
    # Check if user has permission to delete
    if food_item.created_by != request.user and not request.user.is_staff and not request.user.is_superuser:
        messages.error(request, 'You do not have permission to delete this food item.')
        return redirect('hotel:food_item_list')
    
    if request.method == 'POST':
        food_item.delete()
        messages.success(request, 'Food item deleted successfully!')
        return redirect('hotel:food_item_list')
    return render(request, 'food/food_item_confirm_delete.html', {'food_item': food_item})

# Customer Views
@login_required
def create_order(request):
    HotelOrderItemFormSet = inlineformset_factory(
        Order,
        HotelOrderItem,
        form=HotelOrderItemForm,
        extra=1,
        can_delete=False,
        fields=['food_item', 'quantity']
    )

    if request.method == 'POST':
        order = Order(created_by=request.user)

        order_form = OrderForm(request.POST, instance=order)
        item_formset = HotelOrderItemFormSet(request.POST, instance=order, prefix="items")

        if order_form.is_valid() and item_formset.is_valid():
            with transaction.atomic():
                order = order_form.save(commit=False)
                order.created_by = request.user
                order.save()

                instances = item_formset.save(commit=False)

                # ✅ Stock check
                stock_errors = []
                for instance in instances:
                    if hasattr(instance.food_item, "stock_quantity"):
                        available_qty = instance.food_item.stock_quantity
                        if instance.quantity > available_qty:
                            stock_errors.append(
                                f"Only {available_qty} portions of {instance.food_item.name} are available."
                            )

                if stock_errors:
                    # Attach errors so they show in template
                    item_formset.non_form_errors = lambda: stock_errors
                    transaction.set_rollback(True)
                    return render(request, 'food/create_order.html', {
                        'order_form': order_form,
                        'item_formset': item_formset,
                    })

                # ✅ Save valid items and update stock
                for instance in instances:
                    instance.order = order
                    instance.save()
                    if hasattr(instance.food_item, "stock_quantity"):
                        instance.food_item.stock_quantity -= instance.quantity
                        instance.food_item.save()

                messages.success(request, 'Order placed successfully!')
                return redirect('hotel:order_detail', pk=order.pk)
        else:
            # ❌ Removed the generic "Please fix the errors below."
            # Errors will naturally render from formset/order_form in template
            pass
    else:
        order_form = OrderForm()
        item_formset = HotelOrderItemFormSet(queryset=HotelOrderItem.objects.none(), prefix="items")

    return render(request, 'food/create_order.html', {
        'order_form': order_form,
        'item_formset': item_formset,
    })

@login_required
def order_list(request):
    # Get filter parameter (default to 'In Progress' if not specified)
    status_filter = request.GET.get('order_status', 'In Progress')
    
    # Base queryset - only show orders that match the filter
    orders = Order.objects.all().prefetch_related('order_items')
    
    # Apply status filter
    if status_filter:
        orders = orders.filter(order_status=status_filter)
    
    # Calculate totals for each order (fixed the calculation)
    for order in orders:
        # This is the correct way to calculate the total
        total = 0
        for item in order.order_items.all():
            total += item.quantity * item.food_item.price
        order.total_amount = total
    
    return render(request, 'food/order_list.html', {
        'orders': orders,
        'status_filter': status_filter
    })

@login_required
def order_detail(request, pk):
    order = get_object_or_404(Order, pk=pk)
    
    # Calculate order total
    order.total_amount = order.order_items.aggregate(
        total=Sum('quantity') * Sum('food_item__price')
    )['total'] or 0
    
    # Calculate individual item totals
    for item in order.order_items.all():
        item.total_price = item.quantity * item.food_item.price
    
    return render(request, 'food/order_detail.html', {'order': order})
# Add these imports at the top
from django.forms import inlineformset_factory

# Add these view functions
@login_required
def order_edit(request, pk):
    order = get_object_or_404(Order, pk=pk)
    
    # Create formset for order items
    OrderItemFormSet = inlineformset_factory(
        Order, 
        HotelOrderItem, 
        form=HotelOrderItemForm, 
        extra=1, 
        can_delete=True,
        fields=['food_item', 'quantity']  # Explicitly specify fields
    )
    
    if request.method == 'POST':
        form = OrderForm(request.POST, instance=order)
        formset = OrderItemFormSet(request.POST, instance=order, prefix="order_items")
        
        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                form.save()
                instances = formset.save(commit=False)
                
                # Handle deleted items first
                for obj in formset.deleted_objects:
                    # Restore stock for deleted items
                    obj.food_item.quantity += obj.quantity
                    obj.food_item.is_available = True
                    obj.food_item.save()
                    obj.delete()
                
                # Handle changed quantities for existing items
                for form in formset:
                    if form.has_changed() and 'quantity' in form.changed_data and form.instance.pk:
                        order_item = form.instance
                        original_qty = HotelOrderItem.objects.get(pk=order_item.pk).quantity
                        quantity_diff = order_item.quantity - original_qty
                        
                        if quantity_diff != 0:
                            if quantity_diff > 0:
                                # Reduce stock for increased quantity
                                if order_item.food_item.quantity >= quantity_diff:
                                    order_item.food_item.sell(quantity_diff)
                                else:
                                    messages.error(request, f"Not enough stock for {order_item.food_item.name}")
                                    return redirect('hotel:order_edit', pk=order.pk)
                            else:
                                # Add back stock for decreased quantity
                                order_item.food_item.quantity += abs(quantity_diff)
                                order_item.food_item.is_available = True
                                order_item.food_item.save()
                
                # Save all instances
                for instance in instances:
                    instance.save()
                
                messages.success(request, f'Order #{order.id} updated successfully!')
                return redirect('hotel:order_detail', pk=order.pk)
        else:
            # Print form errors for debugging
            print("Form errors:", form.errors)
            print("Formset errors:", formset.errors)
    else:
        form = OrderForm(instance=order)
        formset = OrderItemFormSet(instance=order, prefix="order_items")
    
    # Get available food items for the template
    available_food_items = FoodItem.objects.filter(is_available=True)
    
    return render(request, 'food/order_edit.html', {
        'form': form,
        'formset': formset,
        'order': order,
        'available_food_items': available_food_items,
        'title': f'Edit Order #{order.id}'
    })
@login_required
def order_item_delete(request, order_pk, item_pk):
    order = get_object_or_404(Order, pk=order_pk)
    order_item = get_object_or_404(HotelOrderItem, pk=item_pk, order=order)
    
    if request.method == 'POST':
        # Return stock when deleting order item
        order_item.food_item.quantity += order_item.quantity
        order_item.food_item.is_available = True
        order_item.food_item.save()
        
        order_item.delete()
        messages.success(request, 'Item removed from order successfully!')
        return redirect('hotel:order_edit', pk=order.pk)
    
    return render(request, 'food/order_item_confirm_delete.html', {
        'order': order,
        'order_item': order_item
    })
@login_required
def order_update(request, pk):
    order = get_object_or_404(Order, pk=pk)
    
    if request.method == 'POST':
        new_status = request.POST.get('order_status')
        if new_status in dict(Order.STATUS_CHOICE):
            order.order_status = new_status
            order.save()
            messages.success(request, f'Order #{order.id} status updated to {new_status}')
            return redirect('hotel:order_detail', pk=order.pk)
    
    return redirect('hotel:order_detail', pk=order.pk)

@login_required
def order_delete(request, pk):
    order = get_object_or_404(Order, pk=pk)
    
    if request.method == 'POST':
        order_id = order.id
        order.delete()
        messages.success(request, f'Order #{order_id} has been deleted successfully.')
        return redirect('hotel:order_list')
    
    return render(request, 'food/order_confirm_delete.html', {'order': order})

@login_required
def order_update_ajax(request, pk):
    """AJAX endpoint for updating order status"""
    if request.method == 'POST' and request.headers.get('x-requested-with') == 'XMLHttpRequest':
        order = get_object_or_404(Order, pk=pk)
        new_status = request.POST.get('order_status')
        
        if new_status in dict(Order.STATUS_CHOICE):
            order.order_status = new_status
            order.save()
            
            return JsonResponse({
                'success': True,
                'message': f'Order status updated to {new_status}',
                'new_status': new_status,
                'status_display': order.get_order_status_display()
            })
        
        return JsonResponse({'success': False, 'message': 'Invalid status'})
    
    return JsonResponse({'success': False, 'message': 'Invalid request'})
# API Views
@login_required
def get_food_item_info(request, pk):
    food_item = get_object_or_404(FoodItem, pk=pk, is_available=True)
    return JsonResponse({
        'name': food_item.name,
        'price': str(food_item.price),
        'quantity': food_item.quantity,
        'description': food_item.description,
        'image_url': food_item.image.url if food_item.image else ''
    })