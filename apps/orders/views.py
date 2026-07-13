from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.api import error_response, map_domain_exception
from apps.orders.idempotency import (
    ORDER_RESERVE_OPERATION,
    acquire_idempotency_record,
    complete_idempotency_record,
    fail_idempotency_record,
    request_fingerprint,
    reserve_idempotency_key_required_response,
)
from apps.orders.filters import OrderFilter
from apps.orders.models import Order
from apps.orders.serializers import CancelOrderSerializer, OrderSerializer, OrderWriteSerializer
from apps.orders.services import cancel_order, confirm_order, reserve_order, ship_order


class OrderViewSet(viewsets.ModelViewSet):
    queryset = (
        Order.objects.prefetch_related("items__product", "items__warehouse")
        .all()
        .order_by("-created_at", "-id")
    )
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

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            order = serializer.save()
        except Exception as exc:
            return map_domain_exception(exc)
        return Response(OrderSerializer(order, context=self.get_serializer_context()).data, status=201)

    def partial_update(self, request, *args, **kwargs):
        order = self.get_object()
        serializer = self.get_serializer(order, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            order = serializer.save()
        except Exception as exc:
            return map_domain_exception(exc)
        return Response(OrderSerializer(order, context=self.get_serializer_context()).data)

    def destroy(self, request, *args, **kwargs):
        return error_response(
            "METHOD_NOT_ALLOWED",
            "Orders cannot be deleted through this API.",
            status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    @extend_schema(
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
        responses={
            200: OrderSerializer,
            400: OpenApiResponse(description="Missing Idempotency-Key or validation error."),
            409: OpenApiResponse(description="Idempotency conflict, in-progress duplicate, or domain conflict."),
        },
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
        record, should_process, duplicate_response = acquire_idempotency_record(
            actor=request.user,
            key=idempotency_key,
            order=order,
            fingerprint=fingerprint,
        )

        if duplicate_response is not None:
            return duplicate_response

        if not should_process:
            return Response(record.response_body, status=record.response_status_code)

        try:
            order = reserve_order(order.id, request.user, correlation_id=idempotency_key)
            response = Response(OrderSerializer(order, context=self.get_serializer_context()).data)
        except Exception as exc:
            try:
                response = map_domain_exception(exc)
            except Exception:
                fail_idempotency_record(record)
                raise
            complete_idempotency_record(
                record,
                response_status_code=response.status_code,
                response_body=response.data,
            )
            return response

        complete_idempotency_record(
            record,
            response_status_code=response.status_code,
            response_body=response.data,
        )
        return response

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        try:
            order = confirm_order(self.get_object().id, request.user)
        except Exception as exc:
            return map_domain_exception(exc)
        return Response(OrderSerializer(order, context=self.get_serializer_context()).data)

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
        return Response(OrderSerializer(order, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"])
    def ship(self, request, pk=None):
        try:
            order = ship_order(self.get_object().id, request.user)
        except Exception as exc:
            return map_domain_exception(exc)
        return Response(OrderSerializer(order, context=self.get_serializer_context()).data)
