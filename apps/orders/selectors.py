from datetime import datetime, time, timedelta

from django.db.models import Prefetch, Q, QuerySet
from django.utils import timezone

from apps.orders.models import Order, OrderItem


RESERVATION_EXPIRATION_MINUTES = 30


def expired_reserved_orders_queryset(now=None) -> QuerySet[Order]:
    current_time = now or timezone.now()
    cutoff = current_time - timedelta(minutes=RESERVATION_EXPIRATION_MINUTES)
    return (
        Order.objects.filter(
            status=Order.Status.RESERVED,
            reserved_at__isnull=False,
            reserved_at__lte=cutoff,
        )
        .order_by("reserved_at", "id")
    )


def expired_reserved_order_ids(batch_size: int = 100, now=None) -> list[int]:
    return list(
        expired_reserved_orders_queryset(now=now).values_list("id", flat=True)[:batch_size]
    )


def order_list_queryset():
    return Order.objects.all().order_by("-created_at", "-id")


def orders_with_items_queryset(queryset=None):
    queryset = queryset if queryset is not None else Order.objects.all()
    return queryset.prefetch_related(
        Prefetch(
            "items",
            queryset=OrderItem.objects.select_related("product", "warehouse").order_by("id"),
        )
    )


def filter_orders(queryset, *, q="", status="", created_after=None, created_before=None):
    if q:
        queryset = queryset.filter(
            Q(order_number__icontains=q) | Q(customer_email__icontains=q)
        )
    if status:
        queryset = queryset.filter(status=status)
    if created_after:
        start = timezone.make_aware(
            datetime.combine(created_after, time.min),
            timezone.get_current_timezone(),
        )
        queryset = queryset.filter(created_at__gte=start)
    if created_before:
        end = timezone.make_aware(
            datetime.combine(created_before + timedelta(days=1), time.min),
            timezone.get_current_timezone(),
        )
        queryset = queryset.filter(created_at__lt=end)
    return queryset


def order_detail_queryset():
    return orders_with_items_queryset()
