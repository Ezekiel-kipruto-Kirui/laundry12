# laundry/LaundryApp/forms.py
from django import forms
from unfold.widgets import UnfoldAdminTextInputWidget

class MpesaPaymentForm(forms.Form):
    amount = forms.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        label="Amount to Pay (KSh)",
        widget=UnfoldAdminTextInputWidget(attrs={'placeholder': 'Enter amount'})
    )
    phone_number = forms.CharField(
        max_length=15, 
        label="Customer Phone Number (Safaricom)",
        widget=UnfoldAdminTextInputWidget(attrs={'placeholder': 'e.g., 0712345678'})
    )