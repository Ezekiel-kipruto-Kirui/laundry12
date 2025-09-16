# laundry/LaundryApp/models.py
from __future__ import annotations
import uuid
import logging
from django.db import models, transaction, IntegrityError
from django.db.models import Sum, Count
from django.utils import timezone
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from .sms_utility import send_sms
from phonenumber_field.modelfields import PhoneNumberField
import phonenumbers

logger = logging.getLogger(__name__)

try:
    from django.db.models import JSONField
except Exception:
    from django.contrib.postgres.fields import JSONField

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    SHOP_CHOICES = (
        ('Shop A', 'Shop A'),
        ('Shop B', 'Shop B'),
        
    )
    shop = models.CharField(max_length=50, choices=SHOP_CHOICES, default='None')
    USER_TYPE_CHOICES = (
        ('admin', 'Admin'),
        ('staff', 'Staff'),
    )
    user_type = models.CharField(choices=USER_TYPE_CHOICES)

    
    def __str__(self):
        return f"{self.user.username} - {self.shop}"

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    if hasattr(instance, 'profile'):
        instance.profile.save()
    else:
        UserProfile.objects.create(user=instance)

class Customer(models.Model):
    name = models.CharField(max_length=200)
    phone = PhoneNumberField(region="KE",unique=True)
    address = models.CharField(max_length=255, default='', blank=True)
    created_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='created_customers'
    )
    def __str__(self):
        return f"{self.name} ({self.phone})"

    def clean(self):
        super().clean()
        if self.phone:
            try:
                parsed = phonenumbers.parse(str(self.phone), "KE")
                self.phone = phonenumbers.format_number(
                    parsed, phonenumbers.PhoneNumberFormat.E164
                )
            except phonenumbers.NumberParseException:
                raise ValueError("Invalid phone number format. Example: +254712345678")


class Order(models.Model):
    """Main order model that contains multiple order items"""
    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, related_name='orders',
        help_text="The customer associated with this order."
    )
    uniquecode = models.CharField(max_length=20, unique=True, blank=True, null=False, editable=False)
    
    PAYMENT_TYPE_CHOICES = (
        ('cash', 'Cash'),
        ('mpesa', 'M-Pesa'),
        ('card', 'Credit/Debit Card'),
        ('bank_transfer', 'Bank Transfer'),
        ('other', 'Other'),
        ('pending_payment', 'Pending Payment'),
    )
    payment_type = models.CharField(max_length=50, choices=PAYMENT_TYPE_CHOICES, default='pending_payment', blank=True)

    PAYMENT_STATUS_CHOICES = (
        ('pending', 'pending'),
        ('completed', 'Completed'),
        ('partial', 'Partial'),
        ('failed', 'Failed'),
       
    )
    payment_status = models.CharField(max_length=50, choices=PAYMENT_STATUS_CHOICES, default='pending', blank=True)
    
    SHOP_CHOICE = (
        ('Shop A', 'Shop A'),
        ('Shop B', 'Shop B'),
    )
    shop = models.CharField(max_length=50, choices=SHOP_CHOICE, db_index=True)

    
    delivery_date = models.DateField(db_index=True)
    
    ORDER_STATUS_CHOICES = (
        ('pending', 'Pending'),
       
        ('Completed', 'Completed'),
         ('Delivered', 'Delivered'),
       
    )
    order_status = models.CharField(max_length=50, choices=ORDER_STATUS_CHOICES, default='pending', db_index=True)
    
    
    addressdetails = models.TextField(default='', blank=True)
    
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_price = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False)
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    
    # Store the previous status in the database instead of instance variable
    previous_order_status = models.CharField(max_length=50, blank=True, null=True)

 
    def save(self, *args, **kwargs):
        # Transactional unique code generation to prevent race conditions
        with transaction.atomic():
            if not self.uniquecode:
                prefix = "ORD"
                for _ in range(10):
                    unique_id = uuid.uuid4().hex[:10].upper()
                    new_uniquecode = f"{prefix}-{unique_id}"
                    if not Order.objects.filter(uniquecode=new_uniquecode).exists():
                        self.uniquecode = new_uniquecode
                        break
                else:
                    raise IntegrityError("Could not generate a unique order code after multiple attempts.")
            
            # Calculate balance before saving
            if self.amount_paid == 0:
                self.payment_status = 'pending'
            elif self.balance == 0:
                self.payment_status = 'completed'
            elif self.balance > 0 and self.balance < self.total_price:
                self.payment_status = 'partial'

            
            # Store current status as previous before saving
            if self.pk:
                try:
                    old_instance = Order.objects.get(pk=self.pk)
                    self.previous_order_status = old_instance.order_status
                except Order.DoesNotExist:
                    pass
            
            super().save(*args, **kwargs)

    class Meta:
        verbose_name = "Order"
        verbose_name_plural = "Orders"
        ordering = ['-created_at']

    def __str__(self):
        customer_name = self.customer.name if hasattr(self, 'customer') else "Unknown"
        return f"Order {self.uniquecode} for {customer_name}"


class OrderItem(models.Model):
    """Individual items/services within an order"""
    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, related_name='items',
        help_text="The order this item belongs to."
    )
    
    SERVICE_TYPES = (
        ('Washing', 'Washing'),
        ('Folding', 'Folding'),
        ('Ironing', 'Ironing'),
        ('Dry cleaning', 'Dry cleaning'),
    )
    servicetype = models.CharField(max_length=50, choices=SERVICE_TYPES, default='Washing', db_index=True)
    
    ITEMS_CATEGORY = (
        ('Clothing', 'Clothing'),
        ('Bedding', 'Bedding'),
        ('Household items', 'Household items'),
        ('Footwares', 'Footwares'),
    )
    itemtype = models.CharField(max_length=50, choices=ITEMS_CATEGORY, default='Clothing')
    
    # Changed to TextField to handle multiple comma-separated items
    itemname = models.TextField()
    quantity = models.PositiveIntegerField(default=1)
    
    ITEM_CONDITION_CHOICES = (
        ('new', 'New'),
        ('Old', 'Old'),
        ('Torn', 'Torn'),
    )
    itemcondition = models.CharField(max_length=50, choices=ITEM_CONDITION_CHOICES, default='new', help_text="Condition of the item.")
    
    additional_info = models.TextField(blank=True, null=True)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    total_item_price = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False)
    
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        # Clean up itemname - remove empty values and extra spaces
        if self.itemname:
            # Split by commas, strip whitespace, remove empty strings, then rejoin
            items = [item.strip() for item in self.itemname.split(',') if item.strip()]
            self.itemname = ', '.join(items)
        
        # Calculate total price for this item
        self.total_item_price = (self.unit_price or 0)
        
        super().save(*args, **kwargs)
        
        # Update parent order's total price
        if self.order:
            order_total = self.order.items.aggregate(total=Sum('total_item_price'))['total'] or 0
            self.order.total_price = order_total
            # Update balance after updating total_price
            self.order.balance = self.order.total_price - self.order.amount_paid
            self.order.save(update_fields=['total_price', 'balance'])

    def get_item_list(self):
        """Return item names as a list"""
        if not self.itemname:
            return []
        return [item.strip() for item in self.itemname.split(',') if item.strip()]

    def item_count(self):
        """Return the number of items in this order item"""
        return len(self.get_item_list())

    class Meta:
        verbose_name = "Order Item"
        verbose_name_plural = "Order Items"
        ordering = ['created_at']

    def __str__(self):
        items = self.get_item_list()
        if len(items) > 3:
            return f"{self.quantity} x {', '.join(items[:3])}... ({self.servicetype})"
        return f"{self.quantity} x {', '.join(items)} ({self.servicetype})"


class Payment(models.Model):
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='payment')
    price = models.DecimalField(max_digits=10, decimal_places=2)
    
    class Meta:
        ordering = ['-id']
    
    def __str__(self):
        return f"Payment for {self.order.uniquecode} - KSh {self.price}"

@receiver(post_save, sender=Order)
def handle_order_sms(sender, instance, created, **kwargs):
    customer_phone = str(instance.customer.phone)
    order_code = instance.uniquecode

    if not customer_phone or not customer_phone.startswith('+'):
        logger.warning(f"Could not send SMS for order {order_code}: Invalid customer phone number format.")
        return

    message_body = None
    if created:
        message_body = f"Hello {instance.customer.name}! Your order {order_code} has been received and is now pending."
    
    # Check for status change to 'Completed' using the stored previous status
    if (instance.order_status == 'Completed' and 
        instance.previous_order_status != 'Completed' and
        instance.previous_order_status is not None):
        message_body = f"Hi {instance.customer.name}, your order {order_code} is now complete and delivered! Thank you for your business."
    
    if message_body:
        success, response_message = send_sms(customer_phone, message_body)
        if not success:
            logger.error(f"Failed to send SMS for order {order_code}: {response_message}")