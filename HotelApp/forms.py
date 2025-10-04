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
        fields = ['category', 'name', 'quantity']
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
            # Ensure no availability filtering here
            self.fields['food_item'].queryset = FoodItem.objects.all()
        
    def clean(self):
        cleaned_data = super().clean()
        # Remove any availability/quantity validation
        return cleaned_data
class BulkOrderForm(forms.Form):
    """Form for creating multiple order items at once"""
    items = forms.ModelMultipleChoiceField(
        queryset=FoodItem.objects.filter( quantity__gt=0),  # Add quantity filter
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