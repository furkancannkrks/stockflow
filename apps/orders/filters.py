import django_filters

from apps.orders.models import Order


class OrderFilter(django_filters.FilterSet):
    customer_email = django_filters.CharFilter(
        field_name="customer_email",
        lookup_expr="iexact",
    )
    created_after = django_filters.IsoDateTimeFilter(
        field_name="created_at",
        lookup_expr="gte",
    )
    created_before = django_filters.IsoDateTimeFilter(
        field_name="created_at",
        lookup_expr="lte",
    )
    min_total = django_filters.NumberFilter(
        field_name="total_amount",
        lookup_expr="gte",
    )
    max_total = django_filters.NumberFilter(
        field_name="total_amount",
        lookup_expr="lte",
    )

    class Meta:
        model = Order
        fields = ["status", "customer_email"]
