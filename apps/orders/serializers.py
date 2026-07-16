from rest_framework import serializers

from apps.orders.models import Order, OrderItem
from apps.products.models import Product, Warehouse
from apps.orders.services import save_draft_order


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
    product = serializers.IntegerField(min_value=1)
    warehouse = serializers.IntegerField(min_value=1)
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
        product_ids = {item["product"] for item in items}
        warehouse_ids = {item["warehouse"] for item in items}
        products = Product.objects.in_bulk(product_ids)
        warehouses = Warehouse.objects.in_bulk(warehouse_ids)
        relation_errors = [{} for _item in items]

        for index, item in enumerate(items):
            product_id = item["product"]
            warehouse_id = item["warehouse"]
            if product_id not in products:
                relation_errors[index]["product"] = [
                    f'Invalid pk "{product_id}" - object does not exist.'
                ]
            if warehouse_id not in warehouses:
                relation_errors[index]["warehouse"] = [
                    f'Invalid pk "{warehouse_id}" - object does not exist.'
                ]

        if any(relation_errors):
            raise serializers.ValidationError(relation_errors)

        seen = set()
        duplicates = []
        for item in items:
            product_id = item["product"]
            warehouse_id = item["warehouse"]
            key = (product_id, warehouse_id)
            if key in seen:
                duplicates.append(
                    {
                        "product_id": product_id,
                        "warehouse_id": warehouse_id,
                    }
                )
            seen.add(key)
            item["product"] = products[product_id]
            item["warehouse"] = warehouses[warehouse_id]

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
        return save_draft_order(updates=validated_data, items=items_data)

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
        return save_draft_order(
            order_id=instance.id,
            updates=validated_data,
            items=items_data,
        )


class CancelOrderSerializer(serializers.Serializer):
    reason = serializers.CharField(allow_blank=True, required=False, default=None)
