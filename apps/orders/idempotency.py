import hashlib
import json
from collections.abc import Callable
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response

from apps.api import error_response
from apps.orders.models import IdempotencyRecord, Order


ORDER_RESERVE_OPERATION = "order_reserve"
IDEMPOTENCY_PROCESSING_TIMEOUT = timedelta(minutes=5)
IDEMPOTENCY_RETENTION_PERIOD = timedelta(days=30)


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


def idempotency_failed_response(record: IdempotencyRecord):
    return error_response(
        "IDEMPOTENCY_FAILED",
        (
            "The previous request with this Idempotency-Key failed. "
            "The key can be retried after it expires."
        ),
        details=[
            {
                "operation": record.operation,
                "order_id": record.order_id,
                "status": record.status,
                "expires_at": record.expires_at.isoformat(),
            }
        ],
        status_code=status.HTTP_409_CONFLICT,
    )


def acquire_idempotency_record(
    *,
    actor,
    key: str,
    order: Order,
    fingerprint: str,
    now=None,
):
    current_time = now or timezone.now()
    try:
        with transaction.atomic():
            record = IdempotencyRecord.objects.create(
                actor=actor,
                key=key,
                operation=ORDER_RESERVE_OPERATION,
                order=order,
                request_fingerprint=fingerprint,
                status=IdempotencyRecord.Status.IN_PROGRESS,
                expires_at=current_time + IDEMPOTENCY_PROCESSING_TIMEOUT,
            )
            return record, True, None
    except IntegrityError:
        record = (
            IdempotencyRecord.objects.select_for_update()
            .select_related("order")
            .get(actor=actor, operation=ORDER_RESERVE_OPERATION, key=key)
        )

    if record.expires_at <= current_time:
        _reclaim_expired_record(
            record,
            order=order,
            fingerprint=fingerprint,
            current_time=current_time,
        )
        return record, True, None

    if record.order_id != order.id or record.request_fingerprint != fingerprint:
        return record, False, idempotency_conflict_response(record)

    if record.status == IdempotencyRecord.Status.COMPLETED:
        return record, False, None

    if record.status == IdempotencyRecord.Status.IN_PROGRESS:
        return record, False, idempotency_in_progress_response(record)

    return record, False, idempotency_failed_response(record)


def execute_idempotent_reservation(
    *,
    actor,
    key: str,
    order: Order,
    fingerprint: str,
    execute: Callable[[], Response],
) -> Response:
    with transaction.atomic():
        record, should_process, duplicate_response = acquire_idempotency_record(
            actor=actor,
            key=key,
            order=order,
            fingerprint=fingerprint,
        )

        if duplicate_response is not None:
            return duplicate_response

        if not should_process:
            return Response(
                record.response_body,
                status=record.response_status_code,
            )

        response = execute()
        complete_idempotency_record(
            record,
            response_status_code=response.status_code,
            response_body=response.data,
        )
        return response


def complete_idempotency_record(record: IdempotencyRecord, *, response_status_code: int, response_body):
    record.status = IdempotencyRecord.Status.COMPLETED
    record.response_status_code = response_status_code
    record.response_body = _json_safe(response_body)
    record.expires_at = timezone.now() + IDEMPOTENCY_RETENTION_PERIOD
    record.save(
        update_fields=[
            "status",
            "response_status_code",
            "response_body",
            "expires_at",
            "updated_at",
        ]
    )


def delete_expired_idempotency_records(*, now=None, batch_size: int = 1000) -> int:
    if batch_size <= 0:
        return 0

    current_time = now or timezone.now()
    record_ids = list(
        IdempotencyRecord.objects.filter(expires_at__lte=current_time)
        .order_by("expires_at", "id")
        .values_list("id", flat=True)[:batch_size]
    )
    if not record_ids:
        return 0

    deleted_count, _ = IdempotencyRecord.objects.filter(
        id__in=record_ids,
        expires_at__lte=current_time,
    ).delete()
    return deleted_count


def _reclaim_expired_record(
    record: IdempotencyRecord,
    *,
    order: Order,
    fingerprint: str,
    current_time,
) -> None:
    record.order = order
    record.request_fingerprint = fingerprint
    record.status = IdempotencyRecord.Status.IN_PROGRESS
    record.response_status_code = None
    record.response_body = {}
    record.expires_at = current_time + IDEMPOTENCY_PROCESSING_TIMEOUT
    record.save(
        update_fields=[
            "order",
            "request_fingerprint",
            "status",
            "response_status_code",
            "response_body",
            "expires_at",
            "updated_at",
        ]
    )


def _json_safe(value):
    return json.loads(json.dumps(value, sort_keys=True, default=str))


def _normalize_body(body):
    if not body:
        return {}
    if hasattr(body, "lists"):
        return {key: values for key, values in body.lists()}
    return body
