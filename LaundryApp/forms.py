# LaundryApp/forms.py
from django import forms
from .models import Customer, Order, OrderItem, Payment

class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ['name', 'phone']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Enter customer name'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Enter phone number'
            })
        }

class OrderItemForm(forms.ModelForm):
    class Meta:
        model = OrderItem
        fields = ['servicetype', 'itemtype', 'itemname', 'quantity', 'itemcondition', 'unit_price', 'additional_info']
        widgets = {
            'servicetype': forms.Select(attrs={'class': 'form-select'}),
            'itemtype': forms.Select(attrs={'class': 'form-select'}),
            'itemname': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Enter item name(s), separate multiple with commas'
            }),
            'quantity': forms.NumberInput(attrs={
                'class': 'form-input',
                'min': 1,
                'placeholder': 'Quantity'
            }),
            'itemcondition': forms.Select(attrs={'class': 'form-select'}),
            'unit_price': forms.NumberInput(attrs={
                'class': 'form-input',
                'step': '0.01',
                'min': '0',
                'placeholder': 'Unit price'
            }),
            'additional_info': forms.Textarea(attrs={
                'class': 'form-textarea',
                'rows': 3,
                'placeholder': 'Additional information (optional)'
            }),
        }

class OrderForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ['shop', 'payment_type', 'payment_status', 'delivery_date', 'order_status', 'address', 'addressdetails']
        widgets = {
            'shop': forms.Select(attrs={'class': 'form-select'}),
            'payment_type': forms.Select(attrs={
                'class': 'form-select',
                'id': 'id_payment_type'
            }),
            'payment_status': forms.Select(attrs={
                'class': 'form-select',
                'id': 'id_payment_status'
            }),
            'delivery_date': forms.DateInput(attrs={
                'class': 'form-input',
                'type': 'date'
            }),
            'order_status': forms.Select(attrs={'class': 'form-select'}),
            'address': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Delivery address'
            }),
            'addressdetails': forms.Textarea(attrs={
                'class': 'form-textarea',
                'rows': 3,
                'placeholder': 'Additional address details (optional)'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make payment fields optional
        self.fields['payment_type'].required = False
        self.fields['payment_status'].required = False

class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = ['payment_method', 'transaction_id', 'mpesa_receipt_number', 'phone_number', 'status']
        widgets = {
            'payment_method': forms.Select(attrs={
                'class': 'form-select',
                'id': 'id_payment_method'
            }),
            'transaction_id': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Transaction ID (if applicable)',
                'id': 'id_transaction_id'
            }),
            'mpesa_receipt_number': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'M-Pesa Receipt Number',
                'id': 'id_mpesa_receipt_number'
            }),
            'phone_number': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Phone Number for M-Pesa',
                'id': 'id_phone_number'
            }),
            'status': forms.Select(attrs={
                'class': 'form-select',
                'id': 'id_payment_status_select'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make all fields optional for optional payment
        for field in self.fields:
            self.fields[field].required = False