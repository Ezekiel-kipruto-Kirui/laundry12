# laundry/LaundryApp/models.py
from __future__ import annotations
import uuid
import logging
from django.db import models, transaction, IntegrityError
from django.db.models import Sum
import requests
from django.utils import timezone
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import AbstractUser, BaseUserManager
from .sms_utility import send_sms
from phonenumber_field.modelfields import PhoneNumberField
import phonenumbers
from django.conf import settings
from multiselectfield import MultiSelectField



logger = logging.getLogger(__name__)

try:
    from django.db.models import JSONField
except ImportError:
    from django.contrib.postgres.fields import JSONField
class shoptype(models.Model):
    SHOP_CHOICE = (
        ('Shop A','Shop A'),
        ('Shop B','Shop B'),
        ('Hotel','Hotel')
    )
    shoptype= models.CharField(max_length=50, choices=SHOP_CHOICE)
    def __str__(self):
        return f"{self.shoptype}"
class CustomUserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("The Email field must be set")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self.create_user(email, password, **extra_fields)


class UserProfile(AbstractUser):
    username = None
    email = models.EmailField(unique=True)
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

   
    USER_TYPE_CHOICES = (
        ('admin', 'Admin'),
        ('staff', 'Staff'),
    )
    user_type = models.CharField(max_length=20, choices=USER_TYPE_CHOICES, db_index=True)

    objects = CustomUserManager()

    def __str__(self):
        return f"{self.email} - {self.user_type})"

@receiver(post_save, sender=AbstractUser)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)


@receiver(post_save, sender=AbstractUser)
def save_user_profile(sender, instance, **kwargs):
    if hasattr(instance, 'profile'):
        instance.profile.save()
    else:
        UserProfile.objects.create(user=instance)


class Customer(models.Model):
    name = models.CharField(max_length=200, db_index=True)
    phone = PhoneNumberField(region="KE", unique=True, db_index=True)
    address = models.CharField(max_length=255, default='', blank=True)
    created_by = models.ForeignKey(
    UserProfile,
    # settings.AUTH_USER_MODEL,   # <--- THIS is the fix
        on_delete=models.CASCADE,
        null=True
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
        Customer, on_delete=models.CASCADE, related_name='orders', db_index=True
    )
    uniquecode = models.CharField(max_length=10, unique=True, blank=True, editable=False)

    PAYMENT_TYPE_CHOICES = (
        ('cash', 'Cash'),
        ('mpesa', 'M-Pesa'),
        ('card', 'Credit/Debit Card'),
        ('bank_transfer', 'Bank Transfer'),
        ('other', 'Other'),
        
    )
    payment_type = models.CharField(max_length=50, choices=PAYMENT_TYPE_CHOICES,
                                    default='pending_payment', blank=True, db_index=True)

    PAYMENT_STATUS_CHOICES = (
        ('pending', 'pending'),
        ('completed', 'complete'),
        ('partial', 'partial'),
    )
    payment_status = models.CharField(max_length=50, choices=PAYMENT_STATUS_CHOICES,
                                      default='pending', blank=True, db_index=True)

    SHOP_CHOICE = (
        ('Shop A', 'Shop A'),
        ('Shop B', 'Shop B'),
    )
    shop = models.CharField(max_length=50, choices=SHOP_CHOICE, db_index=True)

    delivery_date = models.DateField(db_index=True)

    ORDER_STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('Completed', 'Completed'),
        ('Delivered_picked', 'Delivered_picked'),
    )
    order_status = models.CharField(max_length=50, choices=ORDER_STATUS_CHOICES,
                                    default='pending', db_index=True)

    addressdetails = models.TextField(default='', blank=True)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_price = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False)
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    created_by = models.CharField(max_length=20, db_index=True)
    previous_order_status = models.CharField(max_length=50, blank=True, null=True)

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if not self.uniquecode:
                prefix = "ORD"
                for _ in range(5):
                    unique_id = uuid.uuid4().hex[:5].upper()
                    new_code = f"{prefix}-{unique_id}"
                    if not Order.objects.filter(uniquecode=new_code).exists():
                        self.uniquecode = new_code
                        break
                else:
                    raise IntegrityError("Could not generate unique order code.")

            # Set payment status
            if self.amount_paid == 0:
                self.payment_status = 'pending'
            elif self.balance == 0:
                self.payment_status = 'completed'
            elif 0 < self.balance < self.total_price:
                self.payment_status = 'partial'

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
        indexes = [
            models.Index(fields=['order_status']),
            models.Index(fields=['payment_status']),
            models.Index(fields=['delivery_date']),
            models.Index(fields=['shop']),
        ]

    def __str__(self):
        customer_name = getattr(self.customer, "name", "Unknown")
        return f"Order {self.uniquecode} for {customer_name}"


class OrderItem(models.Model):
    """Individual items/services within an order"""
    order = models.ForeignKey(Order, on_delete=models.CASCADE,related_name='items', db_index=True)
    SERVICE_TYPES = (
        ('Washing', 'Washing'),
        ('Folding', 'Folding'),
        ('Ironing', 'Ironing'),
        ('Dry cleaning', 'Dry cleaning'),
    )
    servicetype = MultiSelectField(max_length=50, choices=SERVICE_TYPES,
                                   default='Washing', db_index=True)

    ITEMS_CATEGORY = (
        ('Clothing', 'Clothing'),
        ('Bedding', 'Bedding'),
        ('Household items', 'Household items'),
        ('Footwares', 'Footwares'),
    )
    itemtype = models.CharField(max_length=50, choices=ITEMS_CATEGORY,
                                default='Clothing', db_index=True)

    itemname = models.TextField()
    quantity = models.PositiveIntegerField(default=1)
    ITEM_CONDITION_CHOICES = (
        ('new', 'New'),
        ('Old', 'Old'),
        ('Torn', 'Torn'),
    )
    itemcondition = models.CharField(max_length=50, choices=ITEM_CONDITION_CHOICES,
                                     default='new', db_index=True)
    additional_info = models.TextField(blank=True, null=True)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    total_item_price = models.DecimalField(max_digits=12, decimal_places=2,
                                           default=0, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.itemname:
            items = [item.strip() for item in self.itemname.split(',') if item.strip()]
            self.itemname = ', '.join(items)

        self.total_item_price = (self.unit_price or 0)
        super().save(*args, **kwargs)

        # Update order totals only if needed
        if self.order_id:
            order_total = self.order.items.aggregate(total=Sum('total_item_price'))['total'] or 0
            if order_total != self.order.total_price:
                self.order.total_price = order_total
                self.order.balance = self.order.total_price - self.order.amount_paid
                self.order.save(update_fields=['total_price', 'balance'])

    def get_item_list(self):
        return [item.strip() for item in self.itemname.split(',') if item.strip()] if self.itemname else []

    def item_count(self):
        return len(self.get_item_list())

    class Meta:
        verbose_name = "Order Item"
        verbose_name_plural = "Order Items"
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['servicetype']),
            models.Index(fields=['itemtype']),
        ]

    def __str__(self):
        items = self.get_item_list()
        if len(items) > 3:
            return f"{self.quantity} x {', '.join(items[:3])}... ({self.servicetype})"
        return f"{self.quantity} x {', '.join(items)} ({self.servicetype})"


class ExpenseField(models.Model):
    label = models.CharField(max_length=100, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('label',)  # Prevent duplicate labels

    def __str__(self):
        return self.label


class ExpenseRecord(models.Model):
    field = models.ForeignKey(
        ExpenseField, on_delete=models.CASCADE, related_name="records", db_index=True
    )
    shop = models.CharField(max_length=100, choices=Order.SHOP_CHOICE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateField(auto_now_add=True, db_index=True)
    notes = models.CharField(max_length=150, null=True, blank=True)

    def __str__(self):
        return f"{self.field.label}: {self.amount}"


class Payment(models.Model):
    order = models.OneToOneField(Order, on_delete=models.CASCADE,related_name='payment', db_index=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ['-id']

    def __str__(self):
        return f"Payment for {self.order.uniquecode} - KSh {self.price}"


from django.dispatch import receiver


logger = logging.getLogger(__name__)


@receiver(post_save, sender=Order)
def handle_order_sms(sender, instance, created, **kwargs):
    customer_phone = str(instance.customer.phone)
    order_code = instance.uniquecode

    if not customer_phone or not customer_phone.startswith('+'):
        logger.warning(f"⚠️ Invalid phone number for order {order_code}: {customer_phone}")
        return

    message_body = None

    if created:
        message_body = (
            f"Hello {instance.customer.name}! "
            f"Your order {order_code} has been received and is now pending."
        )

    elif instance.order_status == 'Completed' and getattr(instance, "previous_order_status", None) not in (None, 'Completed'):
        message_body = (
            f"Hi {instance.customer.name}, your order {order_code} is now complete! "
            "Thank you for choosing our laundry service."
        )

    elif instance.order_status == 'Delivered_picked' and getattr(instance, "previous_order_status", None) not in (None, 'Delivered_picked'):
        message_body = (
            f"Hello {instance.customer.name}, your order {order_code} has been delivered successfully. "
            "We appreciate your trust in our services!"
        )

    if message_body:
        success, response_message = send_sms(customer_phone, message_body)
        if success:
            logger.info(f"✅ SMS sent for order {order_code}: {response_message}")
        else:
            logger.error(f"❌ Failed to send SMS for order {order_code}: {response_message}")