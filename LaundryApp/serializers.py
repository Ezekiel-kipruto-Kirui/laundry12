# laundry/LaundryApp/serializers.py
from rest_framework import serializers
from .models import Customer, Order, OrderItem
from multiselectfield import MultiSelectField

class MultiSelectFieldSerializer(serializers.Field):
    def to_representation(self, value):
        return value  # DRF displays list of choices
    
    def to_internal_value(self, data):
        if isinstance(data, list):
            return data
        if isinstance(data, str):
            return [data]
        raise serializers.ValidationError("Invalid data type for MultiSelectField")


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = ['id', 'name', 'phone', 'address']

class OrderItemSerializer(serializers.ModelSerializer):
    servicetype = MultiSelectFieldSerializer()

    class Meta:
        model = OrderItem
        fields = [
            'id', 'servicetype', 'itemtype', 'itemname',
            'quantity', 'itemcondition', 'additional_info',
            'unit_price', 'total_item_price'
        ]

class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True)
    customer = serializers.PrimaryKeyRelatedField(queryset=Customer.objects.all())

    class Meta:
        model = Order
        fields = [
            'id', 'customer', 'payment_type', 'payment_status',
            'shop', 'delivery_date', 'order_status',
            'addressdetails', 'amount_paid', 'total_price', 'balance', 'items'
        ]

    def create(self, validated_data):
        items_data = validated_data.pop('items')
        order = Order.objects.create(**validated_data)
        for item_data in items_data:
            OrderItem.objects.create(order=order, **item_data)
        return order
