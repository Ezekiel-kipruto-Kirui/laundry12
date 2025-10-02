import os
from django.db import models
from django.conf import settings
from django.utils import timezone

class FoodCategory(models.Model):
    name = models.CharField(max_length=100, unique=True, db_index=True)

    def __str__(self):
        return self.name


#def food_item_image_path(instance, filename):
    # file will be uploaded to MEDIA_ROOT/food_images/<year>/<month>/<filename>
    #date = timezone.now()
    #return os.path.join('food_images', f"{date.year}", f"{date.month}", filename)
class FoodItem(models.Model):
    category = models.ForeignKey(FoodCategory, on_delete=models.CASCADE, related_name="items")
    name = models.CharField(max_length=100, db_index=True)
   
   

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
        return f"{self.name} - ({'Available' if self.is_available else 'Unavailable'})"

class HotelOrder(models.Model):
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    def __str__(self):
        return f"HotelOrder {self.id} by {self.created_by.username}"

    def get_total(self):
        # Calculate total as quantity * price for each item, then sum
        total = 0
        for item in self.order_items.all():
            total += item.get_total_price()
        return total

# Add this to your HotelOrderItem model
class HotelOrderItem(models.Model):
    order = models.ForeignKey(HotelOrder, on_delete=models.CASCADE, related_name="order_items")
    food_item = models.ForeignKey(FoodItem, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)  # Add this field

   
    def save(self, *args, **kwargs):
        """When order item is saved, reduce stock from FoodItem"""
        # Only reduce stock for new items
        if not self.pk and self.food_item and self.quantity > 0:
            if self.food_item.quantity >= self.quantity:
                self.food_item.sell(self.quantity)
            else:
                raise ValueError(f"Not enough stock for {self.food_item.name}")
                
        super().save(*args, **kwargs)

    def get_total_price(self):
        """Calculate total price for this order item"""
        return self.quantity * self.price

    def __str__(self):
        return f"{self.food_item.name} x {self.quantity} - Ksh{self.get_total_price()}"
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
