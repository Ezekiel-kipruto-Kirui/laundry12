# Create a file called normalize_shops.py in your management/commands directory
# laundry/management/commands/normalize_shops.py
from django.core.management.base import BaseCommand
from django.db import transaction
from LaundryApp.models import Order, UserProfile

class Command(BaseCommand):
    help = 'Normalize all shop values to title case for consistency'
    
    def handle(self, *args, **options):
        with transaction.atomic():
            # Normalize Order shop values
            orders_updated = 0
            for order in Order.objects.all():
                if order.shop and order.shop != order.shop.title():
                    order.shop = order.shop.title()
                    order.save()
                    orders_updated += 1
            
            # Normalize UserProfile shop values (skip "None")
            profiles_updated = 0
            for profile in UserProfile.objects.all():
                if (profile.shop and 
                    profile.shop != "None" and 
                    profile.shop.lower() != "none" and
                    profile.shop != profile.shop.title()):
                    profile.shop = profile.shop.title()
                    profile.save()
                    profiles_updated += 1
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'Successfully normalized {orders_updated} orders and {profiles_updated} profiles'
                )
            )