from drf_spectacular.utils import extend_schema
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
from apps.schema import (
    INVENTORY_ADJUSTMENT_REQUEST_EXAMPLE,
    INVENTORY_ADJUSTMENT_RESPONSE_EXAMPLE,
    api_error_response,
    detail_response,
)
from apps.users.permissions import InventoryPermission


AUTHENTICATION_REQUIRED_RESPONSE = detail_response(
    "Authentication required",
    "Authentication credentials were not provided.",
)
PERMISSION_DENIED_RESPONSE = detail_response(
    "Permission denied",
    "You do not have permission to perform this action.",
)


class InventoryViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = InventorySerializer
    permission_classes = [InventoryPermission]
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

    @extend_schema(
        summary="Adjust inventory",
        description=(
            "Apply stock_in, stock_out, or manual_adjustment through the atomic "
            "inventory adjustment service. Reserved stock remains protected."
        ),
        request=InventoryAdjustmentSerializer,
        responses={
            200: InventorySerializer,
            400: api_error_response(
                "Serializer validation or inventory domain error.",
            ),
            401: AUTHENTICATION_REQUIRED_RESPONSE,
            403: PERMISSION_DENIED_RESPONSE,
            404: api_error_response(
                "No inventory record exists for the product and warehouse.",
            ),
        },
        examples=[
            INVENTORY_ADJUSTMENT_REQUEST_EXAMPLE,
            INVENTORY_ADJUSTMENT_RESPONSE_EXAMPLE,
        ],
        tags=["Inventory"],
    )
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
