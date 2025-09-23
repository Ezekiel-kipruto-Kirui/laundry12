import os
from django.db import models
from django.conf import settings
from django.utils import timezone

class FoodCategory(models.Model):
    name = models.CharField(max_length=100, unique=True, db_index=True)

    def __str__(self):
        return self.name

def food_item_image_path(instance, filename):
    # file will be uploaded to MEDIA_ROOT/food_images/<year>/<month>/<filename>
    date = timezone.now()
    return os.path.join('food_images', f"{date.year}", f"{date.month}", filename)
class FoodItem(models.Model):
    category = models.ForeignKey(FoodCategory, on_delete=models.CASCADE, related_name="items")
    name = models.CharField(max_length=100, db_index=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    image = models.ImageField(upload_to=food_item_image_path, blank=True, null=True)

    # seller who uploaded this food
    created_by =  models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE)
    # stock management
    quantity = models.PositiveIntegerField(default=0)  # how many portions are available
    is_available = models.BooleanField(default=False, db_index=True)  # marked available by seller

    def mark_available(self, qty: int):
        """Seller marks item available with given stock"""
        self.quantity = qty
        self.is_available = True
        self.save()

    def sell(self, qty: int = 1):
        """Reduce stock when a customer orders"""
        if self.quantity >= qty:
            self.quantity -= qty
            if self.quantity == 0:
                self.is_available = False
            self.save()

    def __str__(self):
        return f"{self.name} - {self.price} ({'Available' if self.is_available else 'Unavailable'})"


class Order(models.Model):
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE
    )
    STATUS_CHOICE = [
        ('Served', 'Served'),
        ('In Progress', 'In Progress'),
    ]
    order_status = models.CharField(
        choices=STATUS_CHOICE,
        default='In Progress',   # ✅ fixed mismatch
        db_index=True
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    def __str__(self):
        return f"Order {self.id} by {self.created_by.username}"   # ✅ fixed

    def get_total(self):
        return sum(item.quantity * item.food_item.price for item in self.order_items.all())


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="order_items")
    food_item = models.ForeignKey(FoodItem, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)

    def save(self, *args, **kwargs):
        """When order item is saved, reduce stock from FoodItem"""
        if not self.pk:
            self.food_item.sell(self.quantity)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.food_item.name} x {self.quantity}"
class HotelExpenseField(models.Model):
    label = models.CharField(max_length=100, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('label',)  # Prevent duplicate labels

    def __str__(self):
        return self.label


class HotelExpenseRecord(models.Model):
    field = models.ForeignKey(
        HotelExpenseField, on_delete=models.CASCADE, related_name="records", db_index=True
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateField(auto_now_add=True, db_index=True)
    notes = models.CharField(max_length=150, null=True, blank=True)

    def __str__(self):
        return f"{self.field.label}: {self.amount}"
