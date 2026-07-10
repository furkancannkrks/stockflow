from celery import shared_task

from apps.orders.exceptions import InvalidOrderTransition
from apps.orders.selectors import expired_reserved_order_ids
from apps.orders.services import cancel_order


EXPIRATION_REASON = "Reservation expired after 30 minutes."


@shared_task
def expire_reserved_orders(batch_size: int = 100) -> dict[str, int]:
    expired_count = 0
    skipped_count = 0

    for order_id in expired_reserved_order_ids(batch_size=batch_size):
        try:
            cancel_order(
                order_id,
                performed_by=None,
                source="expiration",
                reason=EXPIRATION_REASON,
            )
        except InvalidOrderTransition:
            skipped_count += 1
        else:
            expired_count += 1

    return {
        "expired": expired_count,
        "skipped": skipped_count,
    }
