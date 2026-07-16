from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError, close_old_connections
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.inventory.models import Inventory, StockMovement
from apps.orders.idempotency import (
    ORDER_RESERVE_OPERATION,
    delete_expired_idempotency_records,
    request_fingerprint,
)
from apps.orders.models import IdempotencyRecord, Order, OrderItem
from apps.orders.services import reserve_order
from apps.products.models import Product, Warehouse
from apps.users.models import User


pytestmark = pytest.mark.django_db


def create_user(username="manager"):
    return User.objects.create_user(
        username=username,
        password="test-password",
        role=User.Role.MANAGER,
    )


@pytest.fixture
def user():
    return create_user()


@pytest.fixture
def client(user):
    api_client = APIClient()
    api_client.force_authenticate(user=user)
    return api_client


def create_product(sku="SKU-1", price="10.00"):
    return Product.objects.create(
        name=f"Product {sku}",
        sku=sku,
        category="General",
        unit_price=Decimal(price),
        low_stock_threshold=1,
    )


def create_warehouse(code="WH-1"):
    return Warehouse.objects.create(
        name=f"Warehouse {code}",
        code=code,
        address="Test address",
    )


def create_order(order_number="ORD-1"):
    return Order.objects.create(
        order_number=order_number,
        customer_name="Customer",
        customer_email="customer@example.com",
    )


def create_reservable_order(order_number="ORD-1", quantity=2, stock=10):
    product = create_product(sku=f"SKU-{order_number}")
    warehouse = create_warehouse(code=f"WH-{order_number}")
    inventory = Inventory.objects.create(product=product, warehouse=warehouse, quantity=stock)
    order = create_order(order_number=order_number)
    OrderItem.objects.create(
        order=order,
        product=product,
        warehouse=warehouse,
        quantity=quantity,
        unit_price=product.unit_price,
        subtotal=Decimal(quantity) * product.unit_price,
    )
    return order, inventory


def test_new_key_reserves_successfully_and_stores_response(client):
    order, inventory = create_reservable_order()

    response = client.post(f"/api/orders/{order.id}/reserve/", HTTP_IDEMPOTENCY_KEY="key-1")

    record = IdempotencyRecord.objects.get()
    inventory.refresh_from_db()
    audit = AuditLog.objects.get()
    assert response.status_code == 200
    assert response.data["status"] == Order.Status.RESERVED
    assert inventory.reserved_quantity == 2
    assert record.status == IdempotencyRecord.Status.COMPLETED
    assert record.response_status_code == 200
    assert record.response_body["status"] == Order.Status.RESERVED
    assert record.expires_at > timezone.now() + timedelta(days=29)
    assert audit.correlation_id == "key-1"


def test_same_key_and_request_replays_without_reserving_again(client):
    order, inventory = create_reservable_order()

    first = client.post(f"/api/orders/{order.id}/reserve/", HTTP_IDEMPOTENCY_KEY="key-2")
    second = client.post(f"/api/orders/{order.id}/reserve/", HTTP_IDEMPOTENCY_KEY="key-2")

    inventory.refresh_from_db()
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.data == first.data
    assert inventory.reserved_quantity == 2
    assert StockMovement.objects.count() == 1
    assert AuditLog.objects.count() == 1


def test_same_key_with_different_order_conflicts(client):
    first_order, first_inventory = create_reservable_order(order_number="ORD-1")
    second_order, second_inventory = create_reservable_order(order_number="ORD-2")

    first = client.post(f"/api/orders/{first_order.id}/reserve/", HTTP_IDEMPOTENCY_KEY="same-key")
    second = client.post(f"/api/orders/{second_order.id}/reserve/", HTTP_IDEMPOTENCY_KEY="same-key")

    second_inventory.refresh_from_db()
    assert first.status_code == 200
    assert second.status_code == 409
    assert second.data["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert second_inventory.reserved_quantity == 0


def test_same_key_with_changed_payload_conflicts(client):
    order, inventory = create_reservable_order()

    first = client.post(f"/api/orders/{order.id}/reserve/", {}, format="json", HTTP_IDEMPOTENCY_KEY="payload-key")
    second = client.post(
        f"/api/orders/{order.id}/reserve/",
        {"unexpected": "value"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="payload-key",
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.data["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_missing_key_follows_documented_policy(client):
    order, inventory = create_reservable_order()

    response = client.post(f"/api/orders/{order.id}/reserve/")

    inventory.refresh_from_db()
    assert response.status_code == 400
    assert response.data["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    assert inventory.reserved_quantity == 0


def test_in_progress_duplicate_returns_conflict(client, user):
    order, inventory = create_reservable_order()
    fingerprint = request_fingerprint(
        method="POST",
        operation=ORDER_RESERVE_OPERATION,
        order_id=order.id,
        body={},
    )
    IdempotencyRecord.objects.create(
        actor=user,
        key="busy-key",
        operation=ORDER_RESERVE_OPERATION,
        order=order,
        request_fingerprint=fingerprint,
        status=IdempotencyRecord.Status.IN_PROGRESS,
    )

    response = client.post(f"/api/orders/{order.id}/reserve/", HTTP_IDEMPOTENCY_KEY="busy-key")

    inventory.refresh_from_db()
    assert response.status_code == 409
    assert response.data["error"]["code"] == "IDEMPOTENCY_IN_PROGRESS"
    assert inventory.reserved_quantity == 0


def test_stale_in_progress_record_is_reclaimed_and_reservation_completes(client, user):
    order, inventory = create_reservable_order()
    fingerprint = request_fingerprint(
        method="POST",
        operation=ORDER_RESERVE_OPERATION,
        order_id=order.id,
        body={},
    )
    record = IdempotencyRecord.objects.create(
        actor=user,
        key="stale-key",
        operation=ORDER_RESERVE_OPERATION,
        order=order,
        request_fingerprint=fingerprint,
        status=IdempotencyRecord.Status.IN_PROGRESS,
        expires_at=timezone.now() - timedelta(seconds=1),
    )

    response = client.post(
        f"/api/orders/{order.id}/reserve/",
        HTTP_IDEMPOTENCY_KEY="stale-key",
    )

    inventory.refresh_from_db()
    record.refresh_from_db()
    assert response.status_code == 200
    assert inventory.reserved_quantity == 2
    assert record.status == IdempotencyRecord.Status.COMPLETED
    assert record.response_status_code == 200
    assert record.expires_at > timezone.now()
    assert StockMovement.objects.count() == 1
    assert AuditLog.objects.count() == 1


def test_stale_in_progress_record_does_not_repeat_legacy_reservation_side_effects(
    client,
    user,
):
    order, inventory = create_reservable_order()
    reserve_order(order.id, user, correlation_id="legacy-stale-key")
    fingerprint = request_fingerprint(
        method="POST",
        operation=ORDER_RESERVE_OPERATION,
        order_id=order.id,
        body={},
    )
    record = IdempotencyRecord.objects.create(
        actor=user,
        key="legacy-stale-key",
        operation=ORDER_RESERVE_OPERATION,
        order=order,
        request_fingerprint=fingerprint,
        status=IdempotencyRecord.Status.IN_PROGRESS,
        expires_at=timezone.now() - timedelta(seconds=1),
    )

    response = client.post(
        f"/api/orders/{order.id}/reserve/",
        HTTP_IDEMPOTENCY_KEY="legacy-stale-key",
    )

    inventory.refresh_from_db()
    record.refresh_from_db()
    assert response.status_code == 409
    assert response.data["error"]["code"] == "INVALID_ORDER_TRANSITION"
    assert inventory.reserved_quantity == 2
    assert StockMovement.objects.count() == 1
    assert AuditLog.objects.count() == 1
    assert record.status == IdempotencyRecord.Status.COMPLETED
    assert record.response_status_code == 409


def test_unexpired_failed_record_is_rejected_without_retry(client, user):
    order, inventory = create_reservable_order()
    fingerprint = request_fingerprint(
        method="POST",
        operation=ORDER_RESERVE_OPERATION,
        order_id=order.id,
        body={},
    )
    IdempotencyRecord.objects.create(
        actor=user,
        key="failed-key",
        operation=ORDER_RESERVE_OPERATION,
        order=order,
        request_fingerprint=fingerprint,
        status=IdempotencyRecord.Status.FAILED,
        expires_at=timezone.now() + timedelta(minutes=5),
    )

    response = client.post(
        f"/api/orders/{order.id}/reserve/",
        HTTP_IDEMPOTENCY_KEY="failed-key",
    )

    inventory.refresh_from_db()
    assert response.status_code == 409
    assert response.data["error"]["code"] == "IDEMPOTENCY_FAILED"
    assert inventory.reserved_quantity == 0
    assert StockMovement.objects.count() == 0
    assert AuditLog.objects.count() == 0


def test_expired_failed_record_is_reclaimed_and_retried(client, user):
    order, inventory = create_reservable_order()
    fingerprint = request_fingerprint(
        method="POST",
        operation=ORDER_RESERVE_OPERATION,
        order_id=order.id,
        body={},
    )
    record = IdempotencyRecord.objects.create(
        actor=user,
        key="expired-failed-key",
        operation=ORDER_RESERVE_OPERATION,
        order=order,
        request_fingerprint=fingerprint,
        status=IdempotencyRecord.Status.FAILED,
        expires_at=timezone.now() - timedelta(seconds=1),
    )

    response = client.post(
        f"/api/orders/{order.id}/reserve/",
        HTTP_IDEMPOTENCY_KEY="expired-failed-key",
    )

    inventory.refresh_from_db()
    record.refresh_from_db()
    assert response.status_code == 200
    assert inventory.reserved_quantity == 2
    assert record.status == IdempotencyRecord.Status.COMPLETED
    assert record.response_status_code == 200
    assert record.expires_at > timezone.now()
    assert StockMovement.objects.count() == 1
    assert AuditLog.objects.count() == 1


def test_failed_reservation_response_is_stored_and_replayed(client):
    order, inventory = create_reservable_order(quantity=5, stock=1)

    first = client.post(f"/api/orders/{order.id}/reserve/", HTTP_IDEMPOTENCY_KEY="fail-key")
    inventory.quantity = 10
    inventory.save(update_fields=["quantity", "updated_at"])
    second = client.post(f"/api/orders/{order.id}/reserve/", HTTP_IDEMPOTENCY_KEY="fail-key")

    inventory.refresh_from_db()
    record = IdempotencyRecord.objects.get()
    assert first.status_code == 409
    assert first.data["error"]["code"] == "INSUFFICIENT_STOCK"
    assert second.status_code == 409
    assert second.data == first.data
    assert record.status == IdempotencyRecord.Status.COMPLETED
    assert inventory.reserved_quantity == 0
    assert StockMovement.objects.count() == 0
    assert AuditLog.objects.count() == 0


def test_completion_failure_rolls_back_reservation_and_idempotency_record(
    client,
    monkeypatch,
):
    order, inventory = create_reservable_order()
    original_save = IdempotencyRecord.save

    def fail_completed_save(self, *args, **kwargs):
        if self.status == IdempotencyRecord.Status.COMPLETED:
            raise RuntimeError("idempotency completion failed")
        return original_save(self, *args, **kwargs)

    monkeypatch.setattr(IdempotencyRecord, "save", fail_completed_save)

    with pytest.raises(RuntimeError, match="idempotency completion failed"):
        client.post(
            f"/api/orders/{order.id}/reserve/",
            HTTP_IDEMPOTENCY_KEY="completion-failure-key",
        )

    order.refresh_from_db()
    inventory.refresh_from_db()
    assert order.status == Order.Status.DRAFT
    assert order.reserved_at is None
    assert inventory.reserved_quantity == 0
    assert IdempotencyRecord.objects.count() == 0
    assert StockMovement.objects.count() == 0
    assert AuditLog.objects.count() == 0


def test_expired_record_cleanup_is_bounded_and_preserves_active_records(user):
    now = timezone.now()
    orders = [
        create_order(order_number=f"CLEANUP-{index}")
        for index in range(3)
    ]
    for index, order in enumerate(orders):
        IdempotencyRecord.objects.create(
            actor=user,
            key=f"cleanup-key-{index}",
            operation=ORDER_RESERVE_OPERATION,
            order=order,
            request_fingerprint=str(index) * 64,
            status=IdempotencyRecord.Status.COMPLETED,
            response_status_code=200,
            response_body={"status": Order.Status.RESERVED},
            expires_at=(
                now - timedelta(minutes=index + 1)
                if index < 2
                else now + timedelta(minutes=5)
            ),
        )

    first_deleted = delete_expired_idempotency_records(now=now, batch_size=1)
    second_deleted = delete_expired_idempotency_records(now=now, batch_size=1)
    third_deleted = delete_expired_idempotency_records(now=now, batch_size=1)

    assert first_deleted == 1
    assert second_deleted == 1
    assert third_deleted == 0
    assert list(
        IdempotencyRecord.objects.values_list("key", flat=True)
    ) == ["cleanup-key-2"]


def test_database_uniqueness_prevents_duplicate_processing(user):
    order, inventory = create_reservable_order()
    fingerprint = "a" * 64
    IdempotencyRecord.objects.create(
        actor=user,
        key="unique-key",
        operation=ORDER_RESERVE_OPERATION,
        order=order,
        request_fingerprint=fingerprint,
    )

    with pytest.raises(IntegrityError):
        IdempotencyRecord.objects.create(
            actor=user,
            key="unique-key",
            operation=ORDER_RESERVE_OPERATION,
            order=order,
            request_fingerprint=fingerprint,
        )


@pytest.mark.django_db(transaction=True)
def test_concurrent_duplicate_requests_do_not_reserve_twice():
    user = create_user(username="concurrent")
    order, inventory = create_reservable_order(order_number="CONCURRENT", quantity=2, stock=10)

    def post_reserve():
        close_old_connections()
        api_client = APIClient()
        api_client.force_authenticate(user=user)
        response = api_client.post(
            f"/api/orders/{order.id}/reserve/",
            HTTP_IDEMPOTENCY_KEY="concurrent-key",
        )
        close_old_connections()
        return response.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(lambda _: post_reserve(), range(2)))

    inventory.refresh_from_db()
    assert statuses.count(200) >= 1
    assert set(statuses).issubset({200, 409})
    assert inventory.reserved_quantity == 2
    assert StockMovement.objects.count() == 1
    assert AuditLog.objects.count() == 1
    assert IdempotencyRecord.objects.count() == 1


def test_openapi_documents_idempotency_header(client):
    response = client.get("/api/schema/")

    assert response.status_code == 200
    schema_text = str(response.data)
    assert "Idempotency-Key" in schema_text
