from django.shortcuts import render,redirect
from django.http import HttpResponse
from django_daraja.mpesa.core import MpesaClient
import json
import logging
# LaundryApp/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from .forms import CustomerForm, OrderForm, OrderItemForm, PaymentForm
from .models import Customer, Order, OrderItem, Payment

logger = logging.getLogger(__name__)

def laundry_form(request):
    # Handle AJAX step submissions
    if request.method == 'POST' and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return handle_step_submission(request)

    if request.method == 'POST':
        # Handle final form submission
        return handle_final_submission(request)

    # GET request - initialize forms
    customer_form = CustomerForm()
    order_form = OrderForm()
    order_item_form = OrderItemForm()
    payment_form = PaymentForm()

    # Clear any existing session data
    if 'order_data' in request.session:
        del request.session['order_data']

    context = {
        'customer_form': customer_form,
        'order_form': order_form,
        'order_item_form': order_item_form,
        'payment_form': payment_form,
    }
    return render(request, 'order_form.html', context)


def handle_step_submission(request):
    """Handle AJAX step submissions"""
    current_step = int(request.POST.get('current_step', 1))
    step_data = request.POST.dict()

    # Remove CSRF token and step flags
    step_data.pop('csrfmiddlewaretoken', None)
    step_data.pop('step_submit', None)
    step_data.pop('current_step', None)

    # Initialize session data if not exists
    if 'order_data' not in request.session:
        request.session['order_data'] = {}

    # Store step data in session
    request.session['order_data'][f'step_{current_step}'] = step_data
    request.session.modified = True

    response_data = {'success': True}

    if current_step == 1:
        # Handle customer step
        customer_form = CustomerForm(step_data)
        if customer_form.is_valid():
            phone = step_data.get('phone')
            name = step_data.get('name')

            # Check if customer exists
            try:
                existing_customer = Customer.objects.get(phone=phone)
                if existing_customer.name != name:
                    # Update name if different
                    existing_customer.name = name
                    existing_customer.save()
                customer_id = existing_customer.id
                response_data['customer_exists'] = True
                response_data['customer_name'] = existing_customer.name
            except Customer.DoesNotExist:
                # Create new customer
                customer = customer_form.save()
                customer_id = customer.id
                response_data['customer_exists'] = False

            # Store customer ID in session
            request.session['order_data']['customer_id'] = customer_id
            request.session.modified = True
        else:
            response_data = {
                'success': False,
                'errors': customer_form.errors
            }

    elif current_step == 2:
        # Validate order form
        order_form = OrderForm(step_data)
        if not order_form.is_valid():
            response_data = {
                'success': False,
                'errors': order_form.errors
            }

    elif current_step == 3:
        # Validate order item form
        order_item_form = OrderItemForm(step_data)
        if not order_item_form.is_valid():
            response_data = {
                'success': False,
                'errors': order_item_form.errors
            }

    elif current_step == 4:
        # Validate payment form
        payment_form = PaymentForm(step_data)
        if not payment_form.is_valid():
            response_data = {
                'success': False,
                'errors': payment_form.errors
            }

    return JsonResponse(response_data)


def handle_final_submission(request):
    """Handle final form submission"""
    if 'order_data' not in request.session:
        messages.error(request, 'Session expired. Please start over.')
        return redirect('laundry_form')

    order_data = request.session['order_data']

    try:
        # Get customer
        customer_id = order_data.get('customer_id')
        if not customer_id:
            messages.error(request, 'Customer information is missing.')
            return redirect('laundry_form')

        customer = Customer.objects.get(id=customer_id)

        # Create order
        step2_data = order_data.get('step_2', {})
        order_form = OrderForm(step2_data)
        if order_form.is_valid():
            order = order_form.save(commit=False)
            order.customer = customer
            order.total_price = 0  # Will be calculated from items

            # Set default payment values if not provided
            if not order.payment_type:
                order.payment_type = 'pending_payment'
            if not order.payment_status:
                order.payment_status = 'pending'

            order.save()
        else:
            messages.error(request, 'Invalid order data.')
            return redirect('laundry_form')

        # Create order item
        step3_data = order_data.get('step_3', {})
        order_item_form = OrderItemForm(step3_data)
        if order_item_form.is_valid():
            order_item = order_item_form.save(commit=False)
            order_item.order = order
            order_item.save()

            # Update order total
            order.total_price = order_item.total_item_price
            order.save()
        else:
            messages.error(request, 'Invalid order item data.')
            return redirect('laundry_form')

        # Create payment only if payment data is provided
        step4_data = order_data.get('step_4', {})
        if step4_data and any(step4_data.values()):  # Check if any payment data is provided
            payment_form = PaymentForm(step4_data)
            if payment_form.is_valid():
                payment = payment_form.save(commit=False)
                payment.order = order
                payment.price = order.total_price
                payment.payment_date = timezone.now()

                # Handle M-Pesa payment
                if payment.payment_method == 'mpesa' and payment.phone_number:
                    try:
                        # Initiate M-Pesa payment
                        payment_result = initiate_mpesa_payment(
                            phone_number=payment.phone_number,
                            amount=order.total_price,
                            order_code=order.uniquecode,
                            request=request
                        )
                        if payment_result['success']:
                            payment.transaction_id = payment_result.get('transaction_id')
                            payment.status = 'pending'
                            messages.info(request, f'M-Pesa payment initiated. Please complete payment on your phone.')
                        else:
                            payment.status = 'failed'
                            messages.warning(request, f'M-Pesa payment failed: {payment_result.get("message", "Unknown error")}')
                    except Exception as e:
                        payment.status = 'failed'
                        messages.warning(request, f'M-Pesa integration error: {str(e)}')

                payment.save()
            else:
                messages.warning(request, 'Payment data provided but invalid. Order created without payment.')

        # Clear session data
        del request.session['order_data']

        messages.success(request, f'Order {order.uniquecode} created successfully!')
        return redirect('laundry_form_success')

    except Exception as e:
        messages.error(request, f'Error creating order: {str(e)}')
        return redirect('laundry_form')


def initiate_mpesa_payment(phone_number, amount, order_code, request):
    """Initiate M-Pesa payment using django-daraja"""
    try:
        cl = MpesaClient()
        # Format phone number for M-Pesa (remove + and ensure it starts with 254)
        formatted_phone = phone_number.replace('+', '')
        if formatted_phone.startswith('0'):
            formatted_phone = '254' + formatted_phone[1:]

        account_reference = f"Order-{order_code}"
        transaction_desc = f"Payment for laundry order {order_code}"

        response = cl.stk_push(
            phone_number=formatted_phone,
            amount=int(amount),
            account_reference=account_reference,
            transaction_desc=transaction_desc,
            callback_url=request.build_absolute_uri('/mpesa/callback/')
        )

        if response.response_code == '0':
            return {
                'success': True,
                'transaction_id': response.checkout_request_id,
                'message': 'M-Pesa payment initiated successfully'
            }
        else:
            return {
                'success': False,
                'message': response.response_description or 'M-Pesa payment failed'
            }
    except Exception as e:
        return {
            'success': False,
            'message': f'M-Pesa error: {str(e)}'
        }

def laundry_form_success(request):
    return render(request, 'form_success.html')

@csrf_exempt
def get_customer_details(request):
    if request.method == 'POST' and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        phone = request.POST.get('phone')
        try:
            customer = Customer.objects.get(phone=phone)
            data = {
                'exists': True,
                'name': customer.name,
                'id': customer.id
            }
        except Customer.DoesNotExist:
            data = {'exists': False}
        return JsonResponse(data)
    return JsonResponse({'error': 'Invalid request'})
def home(request):
    
    return render(request, 'home.html')
def index(request):
    cl = MpesaClient()
    phone_number = '0701396967'
    amount = 1
    account_reference = 'reference'
    transaction_desc = 'Description'
    callback_url = 'https://darajambili.herokuapp.com/express-payment'
    response = cl.stk_push(phone_number, amount, account_reference, transaction_desc, callback_url)
    return HttpResponse('Index')

def stk_push_callback(request):
    """Handle M-Pesa STK Push callback"""
    if request.method == 'POST':
        try:
            # Parse the callback data
            callback_data = json.loads(request.body)

            # Extract relevant information
            merchant_request_id = callback_data.get('Body', {}).get('stkCallback', {}).get('MerchantRequestID')
            checkout_request_id = callback_data.get('Body', {}).get('stkCallback', {}).get('CheckoutRequestID')
            result_code = callback_data.get('Body', {}).get('stkCallback', {}).get('ResultCode')
            result_desc = callback_data.get('Body', {}).get('stkCallback', {}).get('ResultDesc')

            if result_code == 0:
                # Payment successful
                callback_metadata = callback_data.get('Body', {}).get('stkCallback', {}).get('CallbackMetadata', {}).get('Item', [])

                # Extract payment details
                amount = None
                mpesa_receipt_number = None
                transaction_date = None
                phone_number = None

                for item in callback_metadata:
                    if item.get('Name') == 'Amount':
                        amount = item.get('Value')
                    elif item.get('Name') == 'MpesaReceiptNumber':
                        mpesa_receipt_number = item.get('Value')
                    elif item.get('Name') == 'TransactionDate':
                        transaction_date = item.get('Value')
                    elif item.get('Name') == 'PhoneNumber':
                        phone_number = item.get('Value')

                # Update payment record
                try:
                    payment = Payment.objects.get(transaction_id=checkout_request_id)
                    payment.status = 'completed'
                    payment.mpesa_receipt_number = mpesa_receipt_number
                    if transaction_date:
                        # Convert transaction date to datetime
                        from datetime import datetime
                        payment.mpesa_transaction_date = datetime.strptime(str(transaction_date), '%Y%m%d%H%M%S')
                    payment.phone_number = str(phone_number)
                    payment.save()

                    # Update order payment status
                    payment.order.payment_status = 'completed'
                    payment.order.save()

                    logger.info(f'M-Pesa payment completed for order {payment.order.uniquecode}')

                except Payment.DoesNotExist:
                    logger.error(f'Payment record not found for transaction {checkout_request_id}')

            else:
                # Payment failed
                try:
                    payment = Payment.objects.get(transaction_id=checkout_request_id)
                    payment.status = 'failed'
                    payment.save()

                    logger.warning(f'M-Pesa payment failed for order {payment.order.uniquecode}: {result_desc}')

                except Payment.DoesNotExist:
                    logger.error(f'Payment record not found for failed transaction {checkout_request_id}')

            return JsonResponse({'ResultCode': 0, 'ResultDesc': 'Callback received successfully'})

        except Exception as e:
            logger.error(f'Error processing M-Pesa callback: {str(e)}')
            return JsonResponse({'ResultCode': 1, 'ResultDesc': 'Error processing callback'})

    return JsonResponse({'ResultCode': 1, 'ResultDesc': 'Invalid request method'})