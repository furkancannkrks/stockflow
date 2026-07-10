from datetime import timedelta

from django.db.models import QuerySet
from django.utils import timezone

from apps.orders.models import Order


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
