import django_filters
from django.db.models import Q

from apps.products.models import Product
from apps.products.selectors import (
    filter_products_by_low_stock,
    filter_products_by_warehouse,
)


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
        return filter_products_by_warehouse(queryset, value)

    def filter_low_stock(self, queryset, name, value):
        return filter_products_by_low_stock(queryset, value)
