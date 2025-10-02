from django import forms
from django.core.exceptions import ValidationError
from .models import FoodCategory, FoodItem, HotelOrder as Order, HotelOrderItem,HotelExpenseField,HotelExpenseRecord

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
        fields = ['category', 'name', 'quantity', 'is_available']
        widgets = {
            'category': forms.Select(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-white transition duration-200'
            }),
            'name': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-white transition duration-200',
                'placeholder': 'Enter food item name'
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
        fields = []
       

class HotelOrderItemForm(forms.ModelForm):
    class Meta:
        model = HotelOrderItem
        fields = ['food_item', 'quantity', 'price']
        widgets = {
            'food_item': forms.Select(attrs={
                'class': 'w-full p-3 border border-gray-300 rounded-lg'
            }),
            'quantity': forms.NumberInput(attrs={
                'class': 'w-full p-3 border border-gray-300 rounded-lg quantity-input',
                'min': '1'
            }),
            'price': forms.NumberInput(attrs={
                'class': 'w-full p-3 border border-gray-300 rounded-lg price-input',
                'step': '0.01',
                'min': '0'
            })
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make sure the price field is required and has initial value
        if self.instance and self.instance.pk and self.instance.price:
            self.initial['price'] = self.instance.price
        elif not self.initial.get('price'):
            self.initial['price'] = 0.00

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

   


class HotelExpenseRecordForm(forms.ModelForm):
  
    class Meta:
        model = HotelExpenseRecord
        fields = [ 'field', 'amount']
        widgets = {
            'amount': forms.NumberInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'step': '0.01'
            }),
           
            'notes': forms.Textarea(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'rows': 3
            }),
        }


class ExpenseFieldForm(forms.ModelForm):
    class Meta:
        model = HotelExpenseField
        fields = ['label',]
        widgets = {
            'label': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500'
            }),
           
        }

