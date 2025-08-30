from django.shortcuts import render,redirect
from django.http import HttpResponse
from django_daraja.mpesa.core import MpesaClient

def home (request):
    
    return render(request, 'home.html')
def index(request):
    cl = MpesaClient()
    phone_number = '0701396967'
    amount = 1
    account_reference = 'reference'
    transaction_desc = 'Description'
    callback_url = 'https://darajambili.herokuapp.com/express-payment';
    response = cl.stk_push(phone_number, amount, account_reference, transaction_desc, callback_url)
    

def stk_push_callback(request):
        data = request.body
        return HttpResponse("STK Push in Django")