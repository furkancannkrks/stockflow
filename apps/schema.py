from drf_spectacular.utils import OpenApiExample, OpenApiResponse
from rest_framework import serializers


class APIErrorBodySerializer(serializers.Serializer):
    code = serializers.CharField()
    message = serializers.CharField()
    details = serializers.JSONField()


class APIErrorResponseSerializer(serializers.Serializer):
    error = APIErrorBodySerializer()


class DetailResponseSerializer(serializers.Serializer):
    detail = serializers.CharField()


ORDER_RESPONSE_EXAMPLE = {
    "id": 42,
    "order_number": "ORD-2026-1001",
    "customer_name": "Ada Lovelace",
    "customer_email": "ada@example.com",
    "status": "reserved",
    "total_amount": "129.40",
    "reserved_at": "2026-07-16T10:15:00Z",
    "created_at": "2026-07-16T10:10:00Z",
    "updated_at": "2026-07-16T10:15:00Z",
    "items": [
        {
            "id": 81,
            "product": 1,
            "product_sku": "MECH-KB-001",
            "warehouse": 1,
            "warehouse_code": "MAIN",
            "quantity": 1,
            "unit_price": "89.90",
            "subtotal": "89.90",
            "created_at": "2026-07-16T10:10:00Z",
        },
        {
            "id": 82,
            "product": 2,
            "product_sku": "USBC-HUB-001",
            "warehouse": 1,
            "warehouse_code": "MAIN",
            "quantity": 1,
            "unit_price": "39.50",
            "subtotal": "39.50",
            "created_at": "2026-07-16T10:10:00Z",
        },
    ],
}

CREATE_ORDER_REQUEST_EXAMPLE = OpenApiExample(
    "Creating an order",
    value={
        "order_number": "ORD-2026-1001",
        "customer_name": "Ada Lovelace",
        "customer_email": "ada@example.com",
        "items": [
            {"product": 1, "warehouse": 1, "quantity": 1},
            {"product": 2, "warehouse": 1, "quantity": 1},
        ],
    },
    request_only=True,
)

CREATE_ORDER_RESPONSE_EXAMPLE = OpenApiExample(
    "Created order",
    value={**ORDER_RESPONSE_EXAMPLE, "status": "draft", "reserved_at": None},
    response_only=True,
    status_codes=["201"],
)

RESERVE_ORDER_REQUEST_EXAMPLE = OpenApiExample(
    "Reserving an order",
    value={},
    request_only=True,
)

RESERVE_ORDER_RESPONSE_EXAMPLE = OpenApiExample(
    "Reserved order",
    value=ORDER_RESPONSE_EXAMPLE,
    response_only=True,
    status_codes=["200"],
)

IDEMPOTENT_REPLAY_EXAMPLE = OpenApiExample(
    "Successful idempotent replay",
    description=(
        "Repeating the same logical reservation request with the same "
        "Idempotency-Key returns the originally stored response."
    ),
    value=ORDER_RESPONSE_EXAMPLE,
    response_only=True,
    status_codes=["200"],
)

IDEMPOTENCY_CONFLICT_EXAMPLE = OpenApiExample(
    "Idempotency conflict",
    value={
        "error": {
            "code": "IDEMPOTENCY_CONFLICT",
            "message": (
                "Idempotency-Key was already used for a different order or payload."
            ),
            "details": [
                {
                    "operation": "order_reserve",
                    "order_id": 42,
                    "status": "completed",
                }
            ],
        }
    },
    response_only=True,
    status_codes=["409"],
)

INSUFFICIENT_STOCK_EXAMPLE = OpenApiExample(
    "Insufficient stock",
    value={
        "error": {
            "code": "INSUFFICIENT_STOCK",
            "message": "One or more order items do not have enough available stock.",
            "details": [
                {
                    "product_id": 1,
                    "product_sku": "MECH-KB-001",
                    "warehouse_id": 1,
                    "warehouse_code": "MAIN",
                    "requested_quantity": 3,
                    "available_quantity": 2,
                }
            ],
        }
    },
    response_only=True,
    status_codes=["409"],
)

INVALID_TRANSITION_EXAMPLE = OpenApiExample(
    "Invalid transition",
    value={
        "error": {
            "code": "INVALID_ORDER_TRANSITION",
            "message": "The requested order transition is not allowed.",
            "details": [
                {
                    "order_id": 42,
                    "order_number": "ORD-2026-1001",
                    "current_status": "draft",
                    "required_status": "reserved",
                }
            ],
        }
    },
    response_only=True,
    status_codes=["409"],
)

INVENTORY_ADJUSTMENT_REQUEST_EXAMPLE = OpenApiExample(
    "Inventory adjustment",
    value={
        "product_id": 1,
        "warehouse_id": 1,
        "adjustment_type": "stock_in",
        "quantity": 25,
        "description": "Supplier delivery PO-2026-104",
    },
    request_only=True,
)

INVENTORY_ADJUSTMENT_RESPONSE_EXAMPLE = OpenApiExample(
    "Adjusted inventory",
    value={
        "id": 1,
        "product": 1,
        "product_name": "Mechanical Keyboard",
        "product_sku": "MECH-KB-001",
        "warehouse": 1,
        "warehouse_name": "Main Warehouse",
        "warehouse_code": "MAIN",
        "quantity": 35,
        "reserved_quantity": 8,
        "available_quantity": 27,
        "created_at": "2026-07-16T09:00:00Z",
        "updated_at": "2026-07-16T10:30:00Z",
    },
    response_only=True,
    status_codes=["200"],
)

CSV_EXPORT_EXAMPLE = OpenApiExample(
    "CSV export",
    value=(
        "product_id,product_name,sku,category,warehouse_id,warehouse_name,"
        "quantity,reserved_quantity,available_quantity,low_stock_threshold,"
        "generated_at\r\n"
        "1,Mechanical Keyboard,MECH-KB-001,Peripherals,1,Main Warehouse,"
        "10,8,2,5,2026-07-16T10:30:00+00:00\r\n"
    ),
    response_only=True,
    media_type="text/csv",
    status_codes=["200"],
)


def api_error_response(description, *examples):
    return OpenApiResponse(
        response=APIErrorResponseSerializer,
        description=description,
        examples=list(examples),
    )


def detail_response(description, example_detail):
    return OpenApiResponse(
        response=DetailResponseSerializer,
        description=description,
        examples=[
            OpenApiExample(
                description,
                value={"detail": example_detail},
                response_only=True,
            )
        ],
    )
