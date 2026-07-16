import csv

from django.http import StreamingHttpResponse
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.views import APIView

from apps.inventory.selectors import low_stock_inventory
from apps.schema import CSV_EXPORT_EXAMPLE, detail_response
from apps.users.permissions import ManagerOnlyPermission


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
SPREADSHEET_FORMULA_PREFIXES = ("=", "+", "-", "@")


class Echo:
    def write(self, value):
        return value


def spreadsheet_safe_text(value):
    text = str(value)
    if text.startswith(SPREADSHEET_FORMULA_PREFIXES):
        return f"'{text}"
    return text


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
            spreadsheet_safe_text(inventory.product.name),
            spreadsheet_safe_text(inventory.product.sku),
            spreadsheet_safe_text(inventory.product.category),
            inventory.warehouse_id,
            spreadsheet_safe_text(inventory.warehouse.name),
            inventory.quantity,
            inventory.reserved_quantity,
            inventory.available_quantity_value,
            inventory.product.low_stock_threshold,
            generated_at_value,
        ]


class LowStockCSVView(APIView):
    permission_classes = [ManagerOnlyPermission]

    @extend_schema(
        operation_id="export_low_stock_csv",
        description=(
            "Export product-warehouse inventory rows whose available quantity "
            "is less than or equal to the product low-stock threshold. The "
            "response is streamed and includes a timestamped attachment filename."
        ),
        responses={
            (200, "text/csv"): OpenApiResponse(
                response=OpenApiTypes.BINARY,
                description="Low-stock inventory CSV attachment.",
                examples=[CSV_EXPORT_EXAMPLE],
            ),
            401: detail_response(
                "Authentication required",
                "Authentication credentials were not provided.",
            ),
            403: detail_response(
                "Manager role required",
                "You do not have permission to perform this action.",
            ),
        },
        tags=["Reports"],
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
