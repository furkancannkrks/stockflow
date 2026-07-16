import logging

from celery import shared_task
from django.db import InterfaceError, OperationalError

from apps.orders.exceptions import InvalidOrderTransition
from apps.orders.selectors import (
    expired_reserved_order_ids,
    expired_reserved_orders_queryset,
)
from apps.orders.services import cancel_order


EXPIRATION_REASON = "Reservation expired after 30 minutes."
DEFAULT_EXPIRATION_BATCH_SIZE = 100
MAX_EXPIRATION_BATCH_SIZE = 500
EXPIRATION_MAX_RETRIES = 3

logger = logging.getLogger(__name__)


class ExpirationDispatchError(RuntimeError):
    def __init__(self, failed_order_ids):
        self.failed_order_ids = failed_order_ids
        super().__init__(
            f"Could not dispatch expiration tasks for orders: {failed_order_ids}"
        )


@shared_task
def expire_reserved_orders(
    batch_size: int = DEFAULT_EXPIRATION_BATCH_SIZE,
) -> dict[str, int]:
    bounded_batch_size = _bounded_batch_size(batch_size)
    order_ids = expired_reserved_order_ids(batch_size=bounded_batch_size)
    dispatched_count = 0
    failed_order_ids = []

    for order_id in order_ids:
        try:
            expire_reserved_order.delay(order_id)
        except Exception:
            failed_order_ids.append(order_id)
            logger.exception(
                "Failed to dispatch reservation expiration for order %s.",
                order_id,
            )
        else:
            dispatched_count += 1

    if failed_order_ids:
        raise ExpirationDispatchError(failed_order_ids)

    return {"selected": len(order_ids), "dispatched": dispatched_count}


@shared_task(
    autoretry_for=(OperationalError, InterfaceError),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    retry_kwargs={"max_retries": EXPIRATION_MAX_RETRIES},
    acks_late=True,
    reject_on_worker_lost=True,
)
def expire_reserved_order(order_id: int) -> dict[str, int | str]:
    if not expired_reserved_orders_queryset().filter(pk=order_id).exists():
        return {"order_id": order_id, "status": "skipped"}

    try:
        cancel_order(
            order_id,
            performed_by=None,
            source="expiration",
            reason=EXPIRATION_REASON,
        )
    except InvalidOrderTransition:
        return {"order_id": order_id, "status": "skipped"}

    return {"order_id": order_id, "status": "expired"}


def _bounded_batch_size(batch_size: int) -> int:
    if batch_size <= 0:
        return 0
    return min(batch_size, MAX_EXPIRATION_BATCH_SIZE)
