import django_filters
from django.db.models import Exists, OuterRef, Q

from apps.inventory.models import Inventory
from apps.products.models import Product
from apps.products.selectors import annotate_product_low_stock


class ProductFilter(django_filters.FilterSet):
    q = django_filters.CharFilter(method="filter_q")
    category = django_filters.CharFilter(field_name="category", lookup_expr="iexact")
    warehouse = django_filters.NumberFilter(method="filter_warehouse")
    low_stock = django_filters.BooleanFilter(method="filter_low_stock")

    class Meta:
        model = Product
        fields = ["category", "is_active"]

    def filter_q(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(
            Q(name__icontains=value)
            | Q(sku__icontains=value)
            | Q(category__icontains=value)
        )

    def filter_warehouse(self, queryset, name, value):
        warehouse_inventory = Inventory.objects.filter(
            product_id=OuterRef("pk"),
            warehouse_id=value,
        )
        return queryset.annotate(
            has_inventory_in_warehouse=Exists(warehouse_inventory)
        ).filter(has_inventory_in_warehouse=True)

    def filter_low_stock(self, queryset, name, value):
        queryset = annotate_product_low_stock(queryset)
        return queryset.filter(has_low_stock=value)
