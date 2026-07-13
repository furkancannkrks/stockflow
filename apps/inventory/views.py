from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.api import map_domain_exception
from apps.inventory.filters import InventoryFilter
from apps.inventory.models import Inventory
from apps.inventory.serializers import (
    InventoryAdjustmentSerializer,
    InventorySerializer,
    StockMovementSerializer,
)
from apps.inventory.services import adjust_inventory
from apps.inventory.selectors import inventory_with_available_quantity


class InventoryViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = InventorySerializer
    queryset = (
        inventory_with_available_quantity()
        .select_related("product", "warehouse")
        .order_by("product__sku", "warehouse__code")
    )
    filterset_class = InventoryFilter
    ordering_fields = [
        "product__sku",
        "warehouse__code",
        "quantity",
        "reserved_quantity",
        "available_quantity_value",
        "created_at",
        "updated_at",
    ]
    ordering = ["product__sku", "warehouse__code"]

    @action(detail=False, methods=["post"], url_path="adjustments")
    def adjustments(self, request):
        serializer = InventoryAdjustmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            inventory = adjust_inventory(
                product_id=serializer.validated_data["product_id"],
                warehouse_id=serializer.validated_data["warehouse_id"],
                adjustment_type=serializer.validated_data["adjustment_type"],
                quantity=serializer.validated_data["quantity"],
                description=serializer.validated_data.get("description", ""),
                performed_by=request.user,
            )
        except Exception as exc:
            return map_domain_exception(exc)

        return Response(
            InventorySerializer(inventory, context=self.get_serializer_context()).data,
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["get"], url_path="movements")
    def movements(self, request, pk=None):
        inventory = self.get_object()
        movements = inventory.stock_movements.select_related("created_by").all()
        serializer = StockMovementSerializer(movements, many=True)
        return Response(serializer.data)
