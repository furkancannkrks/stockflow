import hashlib
import json

from django.db import IntegrityError, transaction
from rest_framework import status

from apps.api import error_response
from apps.orders.models import IdempotencyRecord, Order


ORDER_RESERVE_OPERATION = "order_reserve"


def request_fingerprint(*, method: str, operation: str, order_id: int, body) -> str:
    payload = {
        "method": method.upper(),
        "operation": operation,
        "order_id": order_id,
        "body": _normalize_body(body),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def reserve_idempotency_key_required_response():
    return error_response(
        "IDEMPOTENCY_KEY_REQUIRED",
        "Idempotency-Key header is required for order reservation.",
        status_code=status.HTTP_400_BAD_REQUEST,
    )


def idempotency_conflict_response(record: IdempotencyRecord):
    return error_response(
        "IDEMPOTENCY_CONFLICT",
        "Idempotency-Key was already used for a different order or payload.",
        details=[
            {
                "operation": record.operation,
                "order_id": record.order_id,
                "status": record.status,
            }
        ],
        status_code=status.HTTP_409_CONFLICT,
    )


def idempotency_in_progress_response(record: IdempotencyRecord):
    return error_response(
        "IDEMPOTENCY_IN_PROGRESS",
        "A request with this Idempotency-Key is still being processed.",
        details=[
            {
                "operation": record.operation,
                "order_id": record.order_id,
                "status": record.status,
            }
        ],
        status_code=status.HTTP_409_CONFLICT,
    )


def acquire_idempotency_record(*, actor, key: str, order: Order, fingerprint: str):
    try:
        with transaction.atomic():
            record = IdempotencyRecord.objects.create(
                actor=actor,
                key=key,
                operation=ORDER_RESERVE_OPERATION,
                order=order,
                request_fingerprint=fingerprint,
                status=IdempotencyRecord.Status.IN_PROGRESS,
            )
            return record, True, None
    except IntegrityError:
        record = (
            IdempotencyRecord.objects.select_related("order")
            .get(actor=actor, operation=ORDER_RESERVE_OPERATION, key=key)
        )

    if record.order_id != order.id or record.request_fingerprint != fingerprint:
        return record, False, idempotency_conflict_response(record)

    if record.status == IdempotencyRecord.Status.COMPLETED:
        return record, False, None

    if record.status == IdempotencyRecord.Status.IN_PROGRESS:
        return record, False, idempotency_in_progress_response(record)

    return record, False, idempotency_in_progress_response(record)


def complete_idempotency_record(record: IdempotencyRecord, *, response_status_code: int, response_body):
    record.status = IdempotencyRecord.Status.COMPLETED
    record.response_status_code = response_status_code
    record.response_body = _json_safe(response_body)
    record.save(update_fields=["status", "response_status_code", "response_body", "updated_at"])


def fail_idempotency_record(record: IdempotencyRecord):
    record.status = IdempotencyRecord.Status.FAILED
    record.save(update_fields=["status", "updated_at"])


def _json_safe(value):
    return json.loads(json.dumps(value, sort_keys=True, default=str))


def _normalize_body(body):
    if not body:
        return {}
    if hasattr(body, "lists"):
        return {key: values for key, values in body.lists()}
    return body
