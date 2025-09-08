# LaundryApp/forms.py
from django import forms
from .models import Customer, Order, OrderItem

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


# laundry/LaundryApp/forms.py
from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm, UserChangeForm, PasswordChangeForm
from django.contrib.auth.models import User, Group
from .models import Customer, Order, OrderItem, UserProfile

class CustomAuthenticationForm(AuthenticationForm):
    """Custom authentication form with additional styling"""
    username = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Username',
            'autocomplete': 'username'
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Password',
            'autocomplete': 'current-password'
        })
    )

    class Meta:
        fields = ['username', 'password']


class UserRegistrationForm(UserCreationForm):
    """Form for user registration with additional fields"""
    email = forms.EmailField(required=True)
    first_name = forms.CharField(max_length=30, required=True)
    last_name = forms.CharField(max_length=30, required=True)
    
    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'password1', 'password2']
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs.update({'class': 'form-control'})


class UserEditForm(forms.ModelForm):
    """Form for editing user information"""
    email = forms.EmailField(required=True)
    
    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name']
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs.update({'class': 'form-control'})


class ProfileEditForm(forms.ModelForm):
    """Form for editing user profile (shop assignment)"""
    class Meta:
        model = UserProfile
        fields = ['shop']
        widgets = {
            'shop': forms.Select(attrs={'class': 'form-control'})
        }


class CustomerForm(forms.ModelForm):
    """Form for customer creation and editing"""
    class Meta:
        model = Customer
        fields = ['name', 'phone']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
        }


class OrderForm(forms.ModelForm):
    """Form for order creation and editing"""
    class Meta:
        model = Order
        fields = ['shop', 'delivery_date', 'payment_type', 'payment_status', 'order_status', 'address', 'addressdetails']
        widgets = {
            'shop': forms.Select(attrs={'class': 'form-control'}),
            'delivery_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'payment_type': forms.Select(attrs={'class': 'form-control'}),
            'payment_status': forms.Select(attrs={'class': 'form-control'}),
            'order_status': forms.Select(attrs={'class': 'form-control'}),
            'address': forms.TextInput(attrs={'class': 'form-control'}),
            'addressdetails': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


class OrderItemForm(forms.ModelForm):
    """Form for order item creation and editing"""
    class Meta:
        model = OrderItem
        fields = ['servicetype', 'itemtype', 'itemname', 'quantity', 'itemcondition', 'unit_price', 'additional_info']
        widgets = {
            'servicetype': forms.Select(attrs={'class': 'form-control'}),
            'itemtype': forms.Select(attrs={'class': 'form-control'}),
            'itemname': forms.TextInput(attrs={'class': 'form-control'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control'}),
            'itemcondition': forms.Select(attrs={'class': 'form-control'}),
            'unit_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'additional_info': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }


class CustomPasswordChangeForm(PasswordChangeForm):
    """Custom password change form with additional styling"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs.update({'class': 'form-control'})
