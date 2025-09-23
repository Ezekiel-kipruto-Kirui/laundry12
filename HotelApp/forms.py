from django import forms
from django.core.exceptions import ValidationError
from .models import FoodCategory, FoodItem, Order, OrderItem,Business,ExpenseField,ExpenseRecord

class FoodCategoryForm(forms.ModelForm):
    class Meta:
        model = FoodCategory
        fields = ['name']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition duration-200',
                'placeholder': 'Enter category name'
            })
        }


class FoodItemForm(forms.ModelForm):
    class Meta:
        model = FoodItem
        fields = ['category', 'name', 'price', 'image', 'quantity', 'is_available']
        widgets = {
            'category': forms.Select(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-white transition duration-200'
            }),
            'name': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-white transition duration-200',
                'placeholder': 'Enter food item name'
            }),
          
            'price': forms.NumberInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-white transition duration-200',
                'placeholder': 'Enter price',
                'step': '0.01',
                'min': '0'
            }),
            'image': forms.ClearableFileInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-white transition duration-200'
            }),
            'quantity': forms.NumberInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-white transition duration-200',
                'placeholder': 'Enter quantity',
                'min': '0'
            }),
            'is_available': forms.CheckboxInput(attrs={
                'class': 'h-5 w-5 text-blue-600 border-gray-300 rounded focus:ring-blue-500'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Set the current user as the created_by field (handled in view)
        self.fields['is_available'].label = "Mark as available"

    def clean_price(self):
        price = self.cleaned_data.get('price')
        if price and price <= 0:
            raise ValidationError("Price must be greater than zero.")
        return price

    def clean_quantity(self):
        quantity = self.cleaned_data.get('quantity')
        if quantity is not None and quantity < 0:
            raise ValidationError("Quantity cannot be negative.")
        return quantity


class FoodItemAvailabilityForm(forms.ModelForm):
    """Form specifically for updating availability and quantity"""
    class Meta:
        model = FoodItem
        fields = ['quantity', 'is_available']
        widgets = {
            'quantity': forms.NumberInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition duration-200',
                'min': '0'
            }),
            'is_available': forms.CheckboxInput(attrs={
                'class': 'h-5 w-5 text-blue-600 border-gray-300 rounded focus:ring-blue-500'
            }),
        }

    def clean_quantity(self):
        quantity = self.cleaned_data.get('quantity')
        if quantity is not None and quantity < 0:
            raise ValidationError("Quantity cannot be negative.")
        return quantity


class OrderForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ['order_status']
        widgets = {
            'order_status': forms.Select(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition duration-200'
            })
        }


class OrderItemForm(forms.ModelForm):
    class Meta:
        model = OrderItem
        fields = ['food_item', 'quantity']
        widgets = {
            'food_item': forms.Select(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition duration-200'
            }),
            'quantity': forms.NumberInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition duration-200',
                'min': '1',
                'value': '1'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only show available food items with stock > 0
        self.fields['food_item'].queryset = FoodItem.objects.filter(
            is_available=True, 
            quantity__gt=0  # This ensures only items with stock are shown
        )

    def clean_quantity(self):
        quantity = self.cleaned_data.get('quantity')
        if quantity < 1:
            raise ValidationError("Quantity must be at least 1.")
        return quantity

    def clean(self):
        cleaned_data = super().clean()
        food_item = cleaned_data.get('food_item')
        quantity = cleaned_data.get('quantity')

        if food_item and quantity:
            if food_item.quantity < quantity:
                raise ValidationError(
                    f"Only {food_item.quantity} portions of {food_item.name} are available."
                )
        return cleaned_data

class BulkOrderForm(forms.Form):
    """Form for creating multiple order items at once"""
    items = forms.ModelMultipleChoiceField(
        queryset=FoodItem.objects.filter(is_available=True, quantity__gt=0),  # Add quantity filter
        widget=forms.CheckboxSelectMultiple,
        label="Select food items"
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Customize the display of each checkbox
        self.fields['items'].label_from_instance = lambda obj: f"{obj.name} - ${obj.price} ({obj.quantity} available)"
class BusinessForm(forms.ModelForm):
    class Meta:
        model = Business
        fields = ['name']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'placeholder': 'Enter business name'
            }),
        }
from django import forms
from .models import Business, ExpenseField, ExpenseRecord

class BusinessForm(forms.ModelForm):
    class Meta:
        model = Business
        fields = ['name']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'placeholder': 'Enter business name'
            }),
        }

class ExpenseFieldForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        business_id = kwargs.pop('business_id', None)
        super().__init__(*args, **kwargs)
        
        if business_id:
            self.fields['business'].queryset = Business.objects.filter(id=business_id)
            self.fields['business'].initial = business_id

    class Meta:
        model = ExpenseField
        fields = ['business', 'label']
        widgets = {
            'business': forms.Select(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500'
            }),
            'label': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'placeholder': 'Enter field name (e.g., Rent, Utilities)'
            }),
        }

class ExpenseRecordForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        business_id = kwargs.pop('business_id', None)
        super().__init__(*args, **kwargs)
        
        if business_id:
            self.fields['business'].queryset = Business.objects.filter(id=business_id)
            self.fields['business'].initial = business_id
            self.fields['expense_field'].queryset = ExpenseField.objects.filter(business_id=business_id)

    class Meta:
        model = ExpenseRecord
        fields = ['business', 'expense_field', 'amount', 'description', 'date']
        widgets = {
            'business': forms.Select(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500'
            }),
            'expense_field': forms.Select(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500'
            }),
            'amount': forms.NumberInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'placeholder': '0.00',
                'step': '0.01'
            }),
            'description': forms.Textarea(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'placeholder': 'Enter description (optional)',
                'rows': 3
            }),
            'date': forms.DateInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'type': 'date'
            }),
        }
    def __init__(self, *args, **kwargs):
        business_id = kwargs.pop('business_id', None)
        super().__init__(*args, **kwargs)
        
        if business_id:
            self.fields['expense_field'].queryset = ExpenseField.objects.filter(business_id=business_id)
            self.fields['business'].initial = business_id

    class Meta:
        model = ExpenseRecord
        fields = ['business', 'expense_field', 'amount', 'description', 'expense_date']
        widgets = {
            'business': forms.Select(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500'
            }),
            'expense_field': forms.Select(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500'
            }),
            'amount': forms.NumberInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'placeholder': 'Enter amount',
                'step': '0.01'
            }),
            'description': forms.Textarea(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'placeholder': 'Enter description (optional)',
                'rows': 3
            }),
            'expense_date': forms.DateInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'type': 'date'
            }),
        }