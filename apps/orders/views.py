from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.api import error_response, map_domain_exception
from apps.orders.models import Order
from apps.orders.serializers import CancelOrderSerializer, OrderSerializer, OrderWriteSerializer
from apps.orders.services import cancel_order, confirm_order, reserve_order, ship_order


class OrderViewSet(viewsets.ModelViewSet):
    queryset = (
        Order.objects.prefetch_related("items__product", "items__warehouse")
        .all()
        .order_by("-created_at", "-id")
    )

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

    @action(detail=True, methods=["post"])
    def reserve(self, request, pk=None):
        try:
            order = reserve_order(self.get_object().id, request.user)
        except Exception as exc:
            return map_domain_exception(exc)
        return Response(OrderSerializer(order, context=self.get_serializer_context()).data)

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
