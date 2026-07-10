from decimal import Decimal

from django.db import transaction
from rest_framework import serializers

from apps.orders.models import Order, OrderItem
from apps.products.models import Product, Warehouse


class OrderItemReadSerializer(serializers.ModelSerializer):
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    warehouse_code = serializers.CharField(source="warehouse.code", read_only=True)

    class Meta:
        model = OrderItem
        fields = [
            "id",
            "product",
            "product_sku",
            "warehouse",
            "warehouse_code",
            "quantity",
            "unit_price",
            "subtotal",
            "created_at",
        ]
        read_only_fields = fields


class OrderItemWriteSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())
    warehouse = serializers.PrimaryKeyRelatedField(queryset=Warehouse.objects.all())
    quantity = serializers.IntegerField(min_value=1)


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemReadSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = [
            "id",
            "order_number",
            "customer_name",
            "customer_email",
            "status",
            "total_amount",
            "reserved_at",
            "created_at",
            "updated_at",
            "items",
        ]
        read_only_fields = [
            "id",
            "status",
            "total_amount",
            "reserved_at",
            "created_at",
            "updated_at",
            "items",
        ]


class OrderWriteSerializer(serializers.ModelSerializer):
    items = OrderItemWriteSerializer(many=True, required=False)

    class Meta:
        model = Order
        fields = ["order_number", "customer_name", "customer_email", "items"]

    def validate_items(self, items):
        seen = set()
        duplicates = []
        for item in items:
            key = (item["product"].id, item["warehouse"].id)
            if key in seen:
                duplicates.append(
                    {
                        "product_id": item["product"].id,
                        "warehouse_id": item["warehouse"].id,
                    }
                )
            seen.add(key)

        if duplicates:
            raise serializers.ValidationError(
                {
                    "code": "DUPLICATE_ORDER_ITEM",
                    "message": "The same product and warehouse cannot appear twice in one order.",
                    "details": duplicates,
                }
            )
        return items

    def create(self, validated_data):
        items_data = validated_data.pop("items", [])
        with transaction.atomic():
            order = Order.objects.create(**validated_data)
            self._replace_items(order, items_data)
            self._recalculate_draft_total(order)
            return order

    def update(self, instance, validated_data):
        if instance.status != Order.Status.DRAFT:
            raise serializers.ValidationError(
                {
                    "code": "ORDER_NOT_EDITABLE",
                    "message": "Only draft orders can be edited.",
                    "details": [{"current_status": instance.status}],
                }
            )

        items_data = validated_data.pop("items", None)
        with transaction.atomic():
            for field, value in validated_data.items():
                setattr(instance, field, value)
            instance.save(update_fields=[*validated_data.keys(), "updated_at"])

            if items_data is not None:
                instance.items.all().delete()
                self._replace_items(instance, items_data)
            self._recalculate_draft_total(instance)
            return instance

    def _replace_items(self, order, items_data):
        for item_data in items_data:
            product = item_data["product"]
            quantity = item_data["quantity"]
            OrderItem.objects.create(
                order=order,
                product=product,
                warehouse=item_data["warehouse"],
                quantity=quantity,
                unit_price=product.unit_price,
                subtotal=Decimal(quantity) * product.unit_price,
            )

    def _recalculate_draft_total(self, order):
        total = sum((item.subtotal for item in order.items.all()), Decimal("0.00"))
        order.total_amount = total
        order.save(update_fields=["total_amount", "updated_at"])


class CancelOrderSerializer(serializers.Serializer):
    reason = serializers.CharField(allow_blank=True, required=False, default=None)
