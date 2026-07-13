from django.db.models import ProtectedError
from rest_framework import status, viewsets
from rest_framework.response import Response

from apps.api import map_domain_exception
from apps.products.filters import ProductFilter
from apps.products.models import Product, Warehouse
from apps.products.serializers import ProductSerializer, WarehouseSerializer
from apps.products.services import update_product


class ProductViewSet(viewsets.ModelViewSet):
    serializer_class = ProductSerializer
    queryset = Product.objects.all().order_by("name", "sku")
    filterset_class = ProductFilter
    ordering_fields = [
        "name",
        "sku",
        "category",
        "unit_price",
        "low_stock_threshold",
        "is_active",
        "created_at",
        "updated_at",
    ]
    ordering = ["name", "sku"]

    def partial_update(self, request, *args, **kwargs):
        product = self.get_object()
        serializer = self.get_serializer(product, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            updated = update_product(product.id, serializer.validated_data, request.user)
        except Exception as exc:
            return map_domain_exception(exc)
        return Response(self.get_serializer(updated).data)

    def destroy(self, request, *args, **kwargs):
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError as exc:
            return map_domain_exception(exc)


class WarehouseViewSet(viewsets.ModelViewSet):
    serializer_class = WarehouseSerializer
    queryset = Warehouse.objects.all().order_by("name", "code")
    http_method_names = ["get", "post", "patch", "head", "options"]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            self.perform_create(serializer)
        except Exception as exc:
            return map_domain_exception(exc)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        try:
            return super().partial_update(request, *args, **kwargs)
        except Exception as exc:
            return map_domain_exception(exc)
