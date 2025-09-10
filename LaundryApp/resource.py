# resources.py
from import_export import resources, fields
from import_export.widgets import ForeignKeyWidget
from .models import Order, Customer

class OrderResource(resources.ModelResource):
    customer_name = fields.Field(
        attribute='customer__name',
        column_name='Customer Name'
    )
    customer_phone = fields.Field(
        attribute='customer__phone',
        column_name='Customer Phone'
    )
    shop_name = fields.Field(
        attribute='shop__name',
        column_name='Shop'
    )
    
    class Meta:
        model = Order
        fields = (
            'uniquecode', 'customer_name', 'customer_phone', 
            'order_status', 'payment_status', 'payment_type',
            'shop_name', 'delivery_date', 'total_price',
            'created_at', 'address', 'addressdetails'
        )
        export_order = fields