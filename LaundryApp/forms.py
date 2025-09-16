
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
        fields = ['shop','user_type']
        widgets = {
            'shop': forms.Select(attrs={'class': 'form-control'}),
            'user_type': forms.Select(attrs={'class': 'form-control'})
        }


class CustomerForm(forms.ModelForm):
    """Form for customer creation and editing"""
    class Meta:
        model = Customer
        fields = ['name', 'phone','address']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'address': forms.TextInput(attrs={'class': 'form-control'}),
        }
    
    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        # Skip uniqueness validation - the view will handle existing customers
        return phone
    
    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        # Check if customer with this phone already exists
        if Customer.objects.filter(phone=phone).exists():
            # If we're in the context of order creation, this is acceptable
            # The view will handle using the existing customer
            return phone
        return phone
class OrderForm(forms.ModelForm):
    """Form for order creation and editing"""
    class Meta:
        model = Order
        fields = ['shop', 'delivery_date', 'payment_type', 'payment_status', 'order_status','amount_paid', 'balance', 'addressdetails']
        widgets = {
            'shop': forms.Select(attrs={'class': 'form-control'}),
            'delivery_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'payment_type': forms.Select(attrs={'class': 'form-control'}),
            'payment_status': forms.Select(attrs={'class': 'form-control'}),
            'order_status': forms.Select(attrs={'class': 'form-control'}),
            
            'addressdetails': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'amount_paid': forms.NumberInput(attrs={'class': 'form-control'}),
            'balance': forms.NumberInput(attrs={'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Set default order status to 'pending'
        self.fields['order_status'].initial = 'pending'
        # Make payment fields optional
        self.fields['payment_type'].required = False
        self.fields['payment_status'].required = False
        self.fields['amount_paid'].required = False
        self.fields['balance'].required = False
# laundry/LaundryApp/forms.py

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
class UserCreateForm(UserCreationForm):
    email = forms.EmailField(required=True)
    first_name = forms.CharField(max_length=30, required=True)
    last_name = forms.CharField(max_length=30, required=True)
    
    SHOP_CHOICES = (
        ('', 'Select Shop'),
        ('Shop A', 'Shop A'),
        ('Shop B', 'Shop B'),
    )
    
    shop = forms.ChoiceField(choices=SHOP_CHOICES, required=False)
    
    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'password1', 'password2', 'is_staff', 'is_active']
    
    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        
        if commit:
            user.save()
            # Create or update user profile
            profile, created = UserProfile.objects.get_or_create(user=user)
            profile.shop = self.cleaned_data['shop']
            profile.save()
        
        return user

