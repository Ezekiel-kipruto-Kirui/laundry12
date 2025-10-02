# HotelApp/resources.py
from import_export import resources, fields
from import_export.widgets import ForeignKeyWidget, ManyToManyWidget
from ..models import HotelOrder, HotelOrderItem

class HotelOrderResource(resources.ModelResource):
    created_by = fields.Field(
        column_name='Created By',
        attribute='created_by',
        widget=ForeignKeyWidget('auth.User', 'username')
    )
    food_items = fields.Field(column_name='Food Items')
    quantities = fields.Field(column_name='Quantities')
    prices = fields.Field(column_name='Prices')
    total_amount = fields.Field(column_name='Total Amount')
    order_date = fields.Field(column_name='Order Date')
    
    class Meta:
        model = HotelOrder
        fields = ('id', 'order_date', 'created_by', 'food_items', 'quantities', 'prices', 'total_amount')
        export_order = ('id', 'order_date', 'created_by', 'food_items', 'quantities', 'prices', 'total_amount')
    
    def dehydrate_food_items(self, order):
        return ' | '.join([item.food_item.name for item in order.order_items.all()])
    
    def dehydrate_quantities(self, order):
        return ' | '.join([str(item.quantity) for item in order.order_items.all()])
    
    def dehydrate_prices(self, order):
        return ' | '.join([f"Ksh {item.price:.2f}" for item in order.order_items.all()])
    
    def dehydrate_total_amount(self, order):
        total = sum(item.quantity * item.price for item in order.order_items.all())
        return f"Ksh {total:.2f}"
    
    def dehydrate_order_date(self, order):
        return order.created_at.strftime('%Y-%m-%d %H:%M')