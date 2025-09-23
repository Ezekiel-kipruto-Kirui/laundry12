from django import forms
from django.contrib.auth.forms import (
    AuthenticationForm,
    UserCreationForm,
    UserChangeForm,
    PasswordChangeForm,
)
from django.contrib.auth import get_user_model

from .models import (
    Customer,
    Order,
    OrderItem,
    UserProfile,
    ExpenseField,
    ExpenseRecord,
    LaundryProfile,
 
)

User = get_user_model()


# ---------------------------
# Authentication / User Forms
# ---------------------------

class CustomAuthenticationForm(AuthenticationForm):
    """Custom authentication form with additional styling"""
    email = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Email',
            'autocomplete': 'email'
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
        fields = ['email', 'password']


class UserEditForm(forms.ModelForm):
    """Form to edit basic user details"""
    class Meta:
        model = User
        fields = ['email', 'first_name', 'last_name']
        labels = {
            'email': 'Email Address',
            'first_name': 'First Name',
            'last_name': 'Last Name',
        }
        widgets = {
            'email': forms.EmailInput(attrs={'class': 'form-control', 'required': True}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
        }


class UserCreateForm(UserCreationForm):
    """Form for creating new users with extended fields"""
    email = forms.EmailField(required=True)
    first_name = forms.CharField(max_length=30, required=True)
    last_name = forms.CharField(max_length=30, required=True)
    user_type = forms.ChoiceField(choices=User.USER_TYPE_CHOICES, required=True)
    app_type = forms.ChoiceField(choices=User.APP_CHOICES, required=True)

    class Meta:
        model = User
        fields = [
            'email',
            'first_name',
            'last_name',
            'user_type',
            'app_type',
            'password1',
            'password2',
            'is_staff',
            'is_active',
        ]

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if email and User.objects.filter(email=email).exists():
            raise forms.ValidationError("A user with this email already exists.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        user.user_type = self.cleaned_data['user_type']
        user.app_type = self.cleaned_data['app_type']
        if commit:
            user.save()
        return user


class ProfileEditForm(forms.ModelForm):
    """Form for editing user profile (role + app assignment)"""
    class Meta:
        model = UserProfile
        fields = ['user_type', 'app_type']
        labels = {
            'user_type': 'User Type',
            'app_type': 'Application Type',
        }
        widgets = {
            'user_type': forms.Select(attrs={'class': 'form-control', 'required': True}),
            'app_type': forms.Select(attrs={'class': 'form-control', 'required': True}),
        }


class LaundryProfileForm(forms.ModelForm):
    """Form for assigning shop to laundry profile"""
    class Meta:
        model = LaundryProfile
        fields = ['shop']
        labels = {
            'shop': 'Shop Assignment',
        }
        widgets = {
            'shop': forms.Select(attrs={'class': 'form-control', 'required': True}),
        }


class CustomPasswordChangeForm(PasswordChangeForm):
    """Custom password change form with additional styling"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs.update({'class': 'form-control'})


# ---------------------------
# Business Forms
# ---------------------------

class CustomerForm(forms.ModelForm):
    """Form for customer creation and editing"""
    class Meta:
        model = Customer
        fields = ['name', 'phone', 'address']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'address': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        # Skip uniqueness validation - handled in view
        return phone


class OrderForm(forms.ModelForm):
    """Form for order creation and editing"""
    class Meta:
        model = Order
        fields = [
            'shop',
            'delivery_date',
            'payment_type',
            'payment_status',
            'order_status',
            'amount_paid',
            'balance',
            'addressdetails'
        ]
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
        # Defaults
        self.fields['order_status'].initial = 'pending'
        # Optional fields
        self.fields['payment_type'].required = False
        self.fields['payment_status'].required = False
        self.fields['amount_paid'].required = False
        self.fields['balance'].required = False


# class OrderItemForm(forms.ModelForm):
#     """Form for order item creation and editing"""
#     class Meta:
#         model = OrderItem
#         fields = [
#             'servicetype',
#             'itemtype',
#             'itemname',
#             'quantity',
#             'itemcondition',
#             'unit_price',
#             'additional_info'
#         ]
#         widgets = {
#             'servicetype': forms.Select(attrs={'class': 'form-control'}),
#             'itemtype': forms.Select(attrs={'class': 'form-control'}),
#             'itemname': forms.TextInput(attrs={'class': 'form-control'}),
#             'quantity': forms.NumberInput(attrs={'class': 'form-control'}),
#             'itemcondition': forms.Select(attrs={'class': 'form-control'}),
#             'unit_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
#             'additional_info': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
#         }

class OrderItemForm(forms.ModelForm):
    class Meta:
        model = OrderItem
        fields = ['servicetype', 'itemtype', 'itemname', 'quantity', 'itemcondition', 'unit_price', 'additional_info']
        widgets = {
            'servicetype': forms.Select(attrs={
                'class': 'w-full px-2 py-1 border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-blue-500 focus:border-blue-500 text-sm h-9'
            }),
            'itemtype': forms.Select(attrs={
                'class': 'w-full px-2 py-1 border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-blue-500 focus:border-blue-500 text-sm h-9'
            }),
            'itemname': forms.TextInput(attrs={
                'class': 'w-full px-2 py-1 border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-blue-500 focus:border-blue-500 text-sm h-9'
            }),
            'quantity': forms.NumberInput(attrs={
                'class': 'w-full px-2 py-1 border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-blue-500 focus:border-blue-500 text-sm h-9'
            }),
            'itemcondition': forms.Select(attrs={
                'class': 'w-full px-2 py-1 border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-blue-500 focus:border-blue-500 text-sm h-9'
            }),
            'unit_price': forms.NumberInput(attrs={
                'class': 'w-full px-2 py-1 border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-blue-500 focus:border-blue-500 text-sm h-9'
            }),
            'additional_info': forms.TextInput(attrs={
                'class': 'w-full px-2 py-1 border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-blue-500 focus:border-blue-500 text-sm h-9'
            }),
        }
# ---------------------------
# Expenses Forms
# ---------------------------

# forms.py



from .models import ExpenseField, ExpenseRecord


# forms.py - Update ExpenseRecordForm
class ExpenseRecordForm(forms.ModelForm):
    class Meta:
        model = ExpenseRecord
        fields = ['field', 'amount', 'notes']  # Remove 'shop' from fields
        widgets = {
            'field': forms.Select(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500'
            }),
            'amount': forms.NumberInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'step': '0.01'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'rows': 3
            }),
        }
    
    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super().__init__(*args, **kwargs)
        
        # Remove shop field from the form since it will be auto-assigned
        if 'shop' in self.fields:
            del self.fields['shop']

class ExpenseFieldForm(forms.ModelForm):
    class Meta:
        model = ExpenseField
        fields = ['label',]
        widgets = {
            'label': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500'
            }),
           
        }

