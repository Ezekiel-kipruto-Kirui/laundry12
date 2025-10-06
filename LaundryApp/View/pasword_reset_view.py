# yourapp/views.py
from django.contrib.auth import views as auth_views
from ..forms import MyPasswordResetForm, MySetPasswordForm

class MyPasswordResetView(auth_views.PasswordResetView):
    form_class = MyPasswordResetForm
    template_name = 'LaundryApp/password_reset_form.html'
    email_template_name = 'LaundryApp/password_reset_email.html'
    success_url = '/password_reset/done/'

class MyPasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    form_class = MySetPasswordForm
    template_name = 'LaundryApp/password_reset_confirm.html'
    success_url = '/reset/done/'
