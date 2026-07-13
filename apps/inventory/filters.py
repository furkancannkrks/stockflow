import django_filters
from django.db.models import F

from apps.inventory.models import Inventory
from apps.inventory.selectors import inventory_with_available_quantity


class InventoryFilter(django_filters.FilterSet):
    product = django_filters.NumberFilter(field_name="product_id")
    warehouse = django_filters.NumberFilter(field_name="warehouse_id")
    low_stock = django_filters.BooleanFilter(method="filter_low_stock")
    out_of_stock = django_filters.BooleanFilter(method="filter_out_of_stock")

    class Meta:
        model = Inventory
        fields = ["product", "warehouse"]

    def _with_available_quantity(self, queryset):
        if "available_quantity_value" in queryset.query.annotations:
            return queryset
        return inventory_with_available_quantity(queryset)

    def filter_low_stock(self, queryset, name, value):
        queryset = self._with_available_quantity(queryset)
        low_stock = queryset.filter(
            available_quantity_value__lte=F("product__low_stock_threshold")
        )
        if value:
            return low_stock
        return queryset.exclude(pk__in=low_stock.values("pk"))

    def filter_out_of_stock(self, queryset, name, value):
        queryset = self._with_available_quantity(queryset)
        if value:
            return queryset.filter(available_quantity_value__lte=0)
        return queryset.filter(available_quantity_value__gt=0)
