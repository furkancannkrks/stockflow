from rest_framework import serializers

from apps.inventory.models import Inventory, StockMovement


class InventorySerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)
    warehouse_code = serializers.CharField(source="warehouse.code", read_only=True)
    available_quantity = serializers.IntegerField(read_only=True)

    class Meta:
        model = Inventory
        fields = [
            "id",
            "product",
            "product_name",
            "product_sku",
            "warehouse",
            "warehouse_name",
            "warehouse_code",
            "quantity",
            "reserved_quantity",
            "available_quantity",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class StockMovementSerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)

    class Meta:
        model = StockMovement
        fields = [
            "id",
            "inventory",
            "movement_type",
            "quantity",
            "reference_type",
            "reference_id",
            "description",
            "created_by",
            "created_by_username",
            "created_at",
        ]
        read_only_fields = fields


class InventoryAdjustmentSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    warehouse_id = serializers.IntegerField()
    adjustment_type = serializers.ChoiceField(
        choices=["stock_in", "stock_out", "manual_adjustment"]
    )
    quantity = serializers.IntegerField(min_value=1)
    description = serializers.CharField(allow_blank=True, required=False, default="")
