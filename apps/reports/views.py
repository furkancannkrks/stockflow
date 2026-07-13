import csv

from django.http import StreamingHttpResponse
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.inventory.selectors import low_stock_inventory


CSV_COLUMNS = [
    "product_id",
    "product_name",
    "sku",
    "category",
    "warehouse_id",
    "warehouse_name",
    "quantity",
    "reserved_quantity",
    "available_quantity",
    "low_stock_threshold",
    "generated_at",
]


class Echo:
    def write(self, value):
        return value


def low_stock_csv_rows(generated_at):
    yield CSV_COLUMNS
    queryset = (
        low_stock_inventory()
        .select_related("product", "warehouse")
        .order_by("product__sku", "warehouse__code")
    )
    generated_at_value = generated_at.isoformat()

    for inventory in queryset.iterator(chunk_size=2000):
        yield [
            inventory.product_id,
            inventory.product.name,
            inventory.product.sku,
            inventory.product.category,
            inventory.warehouse_id,
            inventory.warehouse.name,
            inventory.quantity,
            inventory.reserved_quantity,
            inventory.available_quantity_value,
            inventory.product.low_stock_threshold,
            generated_at_value,
        ]


class LowStockCSVView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="export_low_stock_csv",
        description=(
            "Export product-warehouse inventory rows whose available quantity "
            "is less than or equal to the product low-stock threshold."
        ),
        responses={(200, "text/csv"): OpenApiTypes.BINARY},
    )
    def get(self, request):
        generated_at = timezone.now()
        writer = csv.writer(Echo())
        streaming_content = (
            writer.writerow(row) for row in low_stock_csv_rows(generated_at)
        )
        response = StreamingHttpResponse(
            streaming_content,
            content_type="text/csv",
        )
        filename = f"stockflow-low-stock-{generated_at:%Y%m%d-%H%M%S}.csv"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
