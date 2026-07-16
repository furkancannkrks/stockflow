from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.api import error_response, map_domain_exception
from apps.orders.idempotency import (
    ORDER_RESERVE_OPERATION,
    execute_idempotent_reservation,
    request_fingerprint,
    reserve_idempotency_key_required_response,
)
from apps.orders.filters import OrderFilter
from apps.orders.models import Order
from apps.orders.selectors import orders_with_items_queryset
from apps.orders.serializers import CancelOrderSerializer, OrderSerializer, OrderWriteSerializer
from apps.orders.services import cancel_order, confirm_order, reserve_order, ship_order
from apps.schema import (
    CREATE_ORDER_REQUEST_EXAMPLE,
    CREATE_ORDER_RESPONSE_EXAMPLE,
    IDEMPOTENCY_CONFLICT_EXAMPLE,
    IDEMPOTENT_REPLAY_EXAMPLE,
    INSUFFICIENT_STOCK_EXAMPLE,
    INVALID_TRANSITION_EXAMPLE,
    RESERVE_ORDER_REQUEST_EXAMPLE,
    RESERVE_ORDER_RESPONSE_EXAMPLE,
    api_error_response,
    detail_response,
)
from apps.users.permissions import ReadOnlyOrManagerPermission


AUTHENTICATION_REQUIRED_RESPONSE = detail_response(
    "Authentication required",
    "Authentication credentials were not provided.",
)
PERMISSION_DENIED_RESPONSE = detail_response(
    "Permission denied",
    "You do not have permission to perform this action.",
)
ORDER_NOT_FOUND_RESPONSE = detail_response(
    "Order not found",
    "Not found.",
)


@extend_schema_view(
    create=extend_schema(
        summary="Create a draft order",
        description=(
            "Create a draft order and its items. Product prices, item subtotals, "
            "the order total, and status are calculated by the server."
        ),
        request=OrderWriteSerializer,
        responses={
            201: OrderSerializer,
            400: OpenApiResponse(
                response=OpenApiTypes.OBJECT,
                description="Serializer validation error.",
            ),
            401: AUTHENTICATION_REQUIRED_RESPONSE,
            403: PERMISSION_DENIED_RESPONSE,
            409: api_error_response(
                "The order conflicts with existing data.",
            ),
        },
        examples=[
            CREATE_ORDER_REQUEST_EXAMPLE,
            CREATE_ORDER_RESPONSE_EXAMPLE,
        ],
        tags=["Orders"],
    ),
)
class OrderViewSet(viewsets.ModelViewSet):
    permission_classes = [ReadOnlyOrManagerPermission]
    queryset = Order.objects.all().order_by("-created_at", "-id")
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    filterset_class = OrderFilter
    ordering_fields = [
        "order_number",
        "customer_email",
        "status",
        "total_amount",
        "created_at",
        "updated_at",
    ]
    ordering = ["-created_at", "-id"]

    def get_serializer_class(self):
        if self.action in {"create", "partial_update"}:
            return OrderWriteSerializer
        return OrderSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action in {"list", "retrieve"}:
            return orders_with_items_queryset(queryset)
        return queryset

    def _response_data(self, order):
        hydrated_order = orders_with_items_queryset(
            Order.objects.filter(pk=order.pk)
        ).get()
        return OrderSerializer(
            hydrated_order,
            context=self.get_serializer_context(),
        ).data

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            order = serializer.save()
        except Exception as exc:
            return map_domain_exception(exc)
        return Response(self._response_data(order), status=201)

    def partial_update(self, request, *args, **kwargs):
        order = self.get_object()
        serializer = self.get_serializer(order, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            order = serializer.save()
        except Exception as exc:
            return map_domain_exception(exc)
        return Response(self._response_data(order))

    def destroy(self, request, *args, **kwargs):
        return error_response(
            "METHOD_NOT_ALLOWED",
            "Orders cannot be deleted through this API.",
            status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    @extend_schema(
        summary="Reserve a draft order",
        description=(
            "Atomically reserve inventory for every order item. The "
            "Idempotency-Key is scoped to the authenticated user and reservation "
            "operation. Repeating the same key and logical request replays the "
            "stored status and response body without reserving stock again. "
            "Unexpired in-progress or failed records return a conflict; expired "
            "records are reclaimed and processed as new ownership attempts."
        ),
        parameters=[
            OpenApiParameter(
                name="Idempotency-Key",
                type=str,
                location=OpenApiParameter.HEADER,
                required=True,
                description=(
                    "Unique key scoped to the authenticated user and order reservation "
                    "operation. Reusing the same key and request replays the stored response."
                ),
            )
        ],
        request=OpenApiTypes.OBJECT,
        responses={
            200: OrderSerializer,
            400: api_error_response(
                "The Idempotency-Key header is missing or the request is invalid.",
            ),
            401: AUTHENTICATION_REQUIRED_RESPONSE,
            403: PERMISSION_DENIED_RESPONSE,
            404: ORDER_NOT_FOUND_RESPONSE,
            409: api_error_response(
                "Idempotency conflict, in-progress or failed request, insufficient "
                "stock, or invalid order transition.",
                IDEMPOTENCY_CONFLICT_EXAMPLE,
                INSUFFICIENT_STOCK_EXAMPLE,
                INVALID_TRANSITION_EXAMPLE,
            ),
        },
        examples=[
            RESERVE_ORDER_REQUEST_EXAMPLE,
            RESERVE_ORDER_RESPONSE_EXAMPLE,
            IDEMPOTENT_REPLAY_EXAMPLE,
        ],
        tags=["Orders"],
    )
    @action(detail=True, methods=["post"])
    def reserve(self, request, pk=None):
        idempotency_key = request.headers.get("Idempotency-Key")
        if not idempotency_key:
            return reserve_idempotency_key_required_response()

        order = self.get_object()
        fingerprint = request_fingerprint(
            method=request.method,
            operation=ORDER_RESERVE_OPERATION,
            order_id=order.id,
            body=request.data,
        )

        def execute_reservation():
            try:
                reserved_order = reserve_order(
                    order.id,
                    request.user,
                    correlation_id=idempotency_key,
                )
                return Response(self._response_data(reserved_order))
            except Exception as exc:
                return map_domain_exception(exc)

        return execute_idempotent_reservation(
            actor=request.user,
            key=idempotency_key,
            order=order,
            fingerprint=fingerprint,
            execute=execute_reservation,
        )

    @extend_schema(
        summary="Confirm a reserved order",
        description=(
            "Confirm a reserved order, decreasing physical and reserved inventory "
            "in the same transaction."
        ),
        request=None,
        responses={
            200: OrderSerializer,
            401: AUTHENTICATION_REQUIRED_RESPONSE,
            403: PERMISSION_DENIED_RESPONSE,
            404: ORDER_NOT_FOUND_RESPONSE,
            409: api_error_response(
                "The order cannot be confirmed from its current state.",
                INVALID_TRANSITION_EXAMPLE,
            ),
        },
        tags=["Orders"],
    )
    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        try:
            order = confirm_order(self.get_object().id, request.user)
        except Exception as exc:
            return map_domain_exception(exc)
        return Response(self._response_data(order))

    @extend_schema(
        summary="Cancel a reserved order",
        description=(
            "Cancel a reserved order and release its reserved inventory without "
            "changing physical quantity."
        ),
        request=CancelOrderSerializer,
        responses={
            200: OrderSerializer,
            400: OpenApiResponse(
                response=OpenApiTypes.OBJECT,
                description="Cancellation request validation error.",
            ),
            401: AUTHENTICATION_REQUIRED_RESPONSE,
            403: PERMISSION_DENIED_RESPONSE,
            404: ORDER_NOT_FOUND_RESPONSE,
            409: api_error_response(
                "The order cannot be cancelled from its current state.",
                INVALID_TRANSITION_EXAMPLE,
            ),
        },
        examples=[
            OpenApiExample(
                "Cancel order",
                value={"reason": "Customer requested cancellation."},
                request_only=True,
            )
        ],
        tags=["Orders"],
    )
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        serializer = CancelOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            order = cancel_order(
                self.get_object().id,
                request.user,
                source="manual",
                reason=serializer.validated_data.get("reason"),
            )
        except Exception as exc:
            return map_domain_exception(exc)
        return Response(self._response_data(order))

    @extend_schema(
        summary="Ship a confirmed order",
        description=(
            "Mark a confirmed order as shipped. Inventory is not changed again."
        ),
        request=None,
        responses={
            200: OrderSerializer,
            401: AUTHENTICATION_REQUIRED_RESPONSE,
            403: PERMISSION_DENIED_RESPONSE,
            404: ORDER_NOT_FOUND_RESPONSE,
            409: api_error_response(
                "The order cannot be shipped from its current state.",
                INVALID_TRANSITION_EXAMPLE,
            ),
        },
        tags=["Orders"],
    )
    @action(detail=True, methods=["post"])
    def ship(self, request, pk=None):
        try:
            order = ship_order(self.get_object().id, request.user)
        except Exception as exc:
            return map_domain_exception(exc)
        return Response(self._response_data(order))
