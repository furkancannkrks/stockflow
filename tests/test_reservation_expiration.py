from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from celery.exceptions import Retry
from django.db import InterfaceError, OperationalError
from django.utils import timezone

from apps.inventory.models import Inventory, StockMovement
from apps.orders import tasks as order_tasks
from apps.orders.models import Order, OrderItem
from apps.orders.selectors import expired_reserved_order_ids, expired_reserved_orders_queryset
from apps.orders.tasks import (
    EXPIRATION_MAX_RETRIES,
    EXPIRATION_REASON,
    MAX_EXPIRATION_BATCH_SIZE,
    ExpirationDispatchError,
    expire_reserved_order,
    expire_reserved_orders,
)
from apps.products.models import Product, Warehouse


pytestmark = pytest.mark.django_db


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


def create_order(order_number="ORD-1", status=Order.Status.RESERVED, reserved_at=None):
    return Order.objects.create(
        order_number=order_number,
        customer_name="Test Customer",
        customer_email="customer@example.com",
        status=status,
        total_amount=Decimal("20.00"),
        reserved_at=reserved_at,
    )


def create_order_item(order, product, warehouse, quantity=2, unit_price="10.00"):
    return OrderItem.objects.create(
        order=order,
        product=product,
        warehouse=warehouse,
        quantity=quantity,
        unit_price=Decimal(unit_price),
        subtotal=Decimal(quantity) * Decimal(unit_price),
    )


def create_reserved_order(
    order_number="ORD-1",
    reserved_at=None,
    status=Order.Status.RESERVED,
    quantity=2,
    inventory_quantity=10,
    reserved_quantity=2,
):
    product = create_product(sku=f"SKU-{order_number}")
    warehouse = create_warehouse(code=f"WH-{order_number}")
    inventory = Inventory.objects.create(
        product=product,
        warehouse=warehouse,
        quantity=inventory_quantity,
        reserved_quantity=reserved_quantity,
    )
    order = create_order(order_number=order_number, status=status, reserved_at=reserved_at)
    item = create_order_item(order, product, warehouse, quantity=quantity)
    return order, item, inventory


def test_old_reserved_order_expires_and_releases_reserved_inventory_once():
    old_time = timezone.now() - timedelta(minutes=31)
    order, item, inventory = create_reserved_order(reserved_at=old_time)

    result = expire_reserved_order.run(order.id)

    order.refresh_from_db()
    inventory.refresh_from_db()
    movement = StockMovement.objects.get()

    assert result == {"order_id": order.id, "status": "expired"}
    assert order.status == Order.Status.CANCELLED
    assert order.status != "expired"
    assert inventory.quantity == 10
    assert inventory.reserved_quantity == 0
    assert movement.movement_type == StockMovement.MovementType.RESERVATION_RELEASE
    assert movement.quantity == item.quantity
    assert movement.created_by is None
    assert "source=expiration" in movement.description
    assert f"reason={EXPIRATION_REASON}" in movement.description


def test_recent_reserved_order_does_not_expire():
    recent_time = timezone.now() - timedelta(minutes=29)
    order, item, inventory = create_reserved_order(reserved_at=recent_time)

    result = expire_reserved_order.run(order.id)

    order.refresh_from_db()
    inventory.refresh_from_db()
    assert result == {"order_id": order.id, "status": "skipped"}
    assert order.status == Order.Status.RESERVED
    assert inventory.reserved_quantity == 2
    assert StockMovement.objects.count() == 0


def test_confirmed_order_does_not_expire():
    old_time = timezone.now() - timedelta(minutes=31)
    order, item, inventory = create_reserved_order(
        reserved_at=old_time,
        status=Order.Status.CONFIRMED,
        reserved_quantity=0,
    )

    result = expire_reserved_order.run(order.id)

    order.refresh_from_db()
    assert result == {"order_id": order.id, "status": "skipped"}
    assert order.status == Order.Status.CONFIRMED
    assert StockMovement.objects.count() == 0


def test_cancelled_order_does_not_expire_again():
    old_time = timezone.now() - timedelta(minutes=31)
    order, item, inventory = create_reserved_order(
        reserved_at=old_time,
        status=Order.Status.CANCELLED,
        reserved_quantity=0,
    )

    result = expire_reserved_order.run(order.id)

    order.refresh_from_db()
    assert result == {"order_id": order.id, "status": "skipped"}
    assert order.status == Order.Status.CANCELLED
    assert StockMovement.objects.count() == 0


@pytest.mark.parametrize("status", [Order.Status.DRAFT, Order.Status.SHIPPED])
def test_other_non_reserved_orders_are_skipped(status):
    old_time = timezone.now() - timedelta(minutes=31)
    order, item, inventory = create_reserved_order(
        reserved_at=old_time,
        status=status,
        reserved_quantity=0,
    )

    result = expire_reserved_order.run(order.id)

    order.refresh_from_db()
    inventory.refresh_from_db()
    assert result == {"order_id": order.id, "status": "skipped"}
    assert order.status == status
    assert inventory.quantity == 10
    assert inventory.reserved_quantity == 0
    assert StockMovement.objects.count() == 0


def test_repeated_task_execution_does_not_release_twice_or_duplicate_movements():
    old_time = timezone.now() - timedelta(minutes=31)
    order, item, inventory = create_reserved_order(reserved_at=old_time)

    first_result = expire_reserved_order.run(order.id)
    second_result = expire_reserved_order.run(order.id)

    order.refresh_from_db()
    inventory.refresh_from_db()
    assert first_result == {"order_id": order.id, "status": "expired"}
    assert second_result == {"order_id": order.id, "status": "skipped"}
    assert order.status == Order.Status.CANCELLED
    assert inventory.quantity == 10
    assert inventory.reserved_quantity == 0
    assert StockMovement.objects.count() == 1


def test_rollback_leaves_state_unchanged_when_expiration_release_fails(monkeypatch):
    old_time = timezone.now() - timedelta(minutes=31)
    order, item, inventory = create_reserved_order(reserved_at=old_time)

    def fail_bulk_create(movements):
        raise RuntimeError("movement write failed")

    monkeypatch.setattr(StockMovement.objects, "bulk_create", fail_bulk_create)

    with pytest.raises(RuntimeError, match="movement write failed"):
        expire_reserved_order.run(order.id)

    order.refresh_from_db()
    inventory.refresh_from_db()
    assert order.status == Order.Status.RESERVED
    assert inventory.quantity == 10
    assert inventory.reserved_quantity == 2
    assert StockMovement.objects.count() == 0


def test_timezone_aware_cutoff_selects_eligible_order():
    now = timezone.now()
    assert timezone.is_aware(now)
    old_order, item, inventory = create_reserved_order(
        order_number="OLD",
        reserved_at=now - timedelta(minutes=30, seconds=1),
    )
    recent_order, recent_item, recent_inventory = create_reserved_order(
        order_number="RECENT",
        reserved_at=now - timedelta(minutes=29, seconds=59),
    )

    selected_ids = expired_reserved_order_ids(now=now)

    assert selected_ids == [old_order.id]


def test_synchronous_service_level_expiration_path_uses_cancellation_service():
    old_time = timezone.now() - timedelta(minutes=31)
    order, item, inventory = create_reserved_order(reserved_at=old_time)

    expire_reserved_order.run(order.id)

    order.refresh_from_db()
    inventory.refresh_from_db()
    movement = StockMovement.objects.get()
    assert order.status == Order.Status.CANCELLED
    assert inventory.reserved_quantity == 0
    assert movement.movement_type == StockMovement.MovementType.RESERVATION_RELEASE
    assert "source=expiration" in movement.description


def test_dispatcher_enqueues_only_the_bounded_eligible_batch(monkeypatch):
    now = timezone.now()
    older, _, _ = create_reserved_order(
        order_number="DISPATCH-OLDER",
        reserved_at=now - timedelta(minutes=40),
    )
    newer, _, _ = create_reserved_order(
        order_number="DISPATCH-NEWER",
        reserved_at=now - timedelta(minutes=35),
    )
    create_reserved_order(
        order_number="DISPATCH-RECENT",
        reserved_at=now - timedelta(minutes=5),
    )
    dispatched_order_ids = []
    monkeypatch.setattr(
        expire_reserved_order,
        "delay",
        dispatched_order_ids.append,
    )

    result = expire_reserved_orders.run(batch_size=2)

    assert result == {"selected": 2, "dispatched": 2}
    assert dispatched_order_ids == [older.id, newer.id]
    assert Order.objects.filter(status=Order.Status.RESERVED).count() == 3
    assert StockMovement.objects.count() == 0


def test_dispatcher_caps_requested_batch_size(monkeypatch):
    selected_batch_sizes = []

    def capture_batch_size(batch_size):
        selected_batch_sizes.append(batch_size)
        return []

    monkeypatch.setattr(
        order_tasks,
        "expired_reserved_order_ids",
        capture_batch_size,
    )

    result = expire_reserved_orders.run(
        batch_size=MAX_EXPIRATION_BATCH_SIZE + 100,
    )

    assert result == {"selected": 0, "dispatched": 0}
    assert selected_batch_sizes == [MAX_EXPIRATION_BATCH_SIZE]


def test_dispatcher_attempts_later_orders_before_reporting_failure(monkeypatch):
    now = timezone.now()
    first, _, _ = create_reserved_order(
        order_number="DISPATCH-FAIL",
        reserved_at=now - timedelta(minutes=40),
    )
    second, _, _ = create_reserved_order(
        order_number="DISPATCH-CONTINUE",
        reserved_at=now - timedelta(minutes=35),
    )
    attempted_order_ids = []

    def dispatch_with_failure(order_id):
        attempted_order_ids.append(order_id)
        if order_id == first.id:
            raise RuntimeError("broker dispatch failed")

    monkeypatch.setattr(expire_reserved_order, "delay", dispatch_with_failure)

    with pytest.raises(ExpirationDispatchError) as exc_info:
        expire_reserved_orders.run(batch_size=2)

    assert attempted_order_ids == [first.id, second.id]
    assert exc_info.value.failed_order_ids == [first.id]


def test_unexpected_per_order_failure_does_not_block_another_order(monkeypatch):
    old_time = timezone.now() - timedelta(minutes=31)
    failing, _, failing_inventory = create_reserved_order(
        order_number="PER-ORDER-FAIL",
        reserved_at=old_time,
    )
    successful, _, successful_inventory = create_reserved_order(
        order_number="PER-ORDER-SUCCESS",
        reserved_at=old_time,
    )
    real_cancel_order = order_tasks.cancel_order

    def fail_one_order(order_id, *args, **kwargs):
        if order_id == failing.id:
            raise RuntimeError("unexpected expiration failure")
        return real_cancel_order(order_id, *args, **kwargs)

    monkeypatch.setattr(order_tasks, "cancel_order", fail_one_order)

    with pytest.raises(RuntimeError, match="unexpected expiration failure"):
        expire_reserved_order.run(failing.id)
    successful_result = expire_reserved_order.run(successful.id)

    failing.refresh_from_db()
    successful.refresh_from_db()
    failing_inventory.refresh_from_db()
    successful_inventory.refresh_from_db()
    assert failing.status == Order.Status.RESERVED
    assert failing_inventory.reserved_quantity == 2
    assert successful_result == {
        "order_id": successful.id,
        "status": "expired",
    }
    assert successful.status == Order.Status.CANCELLED
    assert successful_inventory.reserved_quantity == 0
    assert StockMovement.objects.count() == 1


def test_transient_database_errors_use_bounded_retry(monkeypatch):
    old_time = timezone.now() - timedelta(minutes=31)
    order, _, inventory = create_reserved_order(reserved_at=old_time)

    def raise_transient_error(*args, **kwargs):
        raise OperationalError("database lock timeout")

    monkeypatch.setattr(order_tasks, "cancel_order", raise_transient_error)

    with patch.object(
        expire_reserved_order,
        "retry",
        side_effect=Retry(),
    ) as retry:
        with pytest.raises(Retry):
            expire_reserved_order.run(order.id)

    assert expire_reserved_order.autoretry_for == (OperationalError, InterfaceError)
    assert retry.call_count == 1
    retry_kwargs = retry.call_args.kwargs
    assert retry_kwargs["max_retries"] == EXPIRATION_MAX_RETRIES
    assert 0 <= retry_kwargs["countdown"] <= 60
    assert isinstance(retry_kwargs["exc"], OperationalError)
    order.refresh_from_db()
    inventory.refresh_from_db()
    assert order.status == Order.Status.RESERVED
    assert inventory.reserved_quantity == 2
    assert StockMovement.objects.count() == 0


def test_periodic_selector_returns_only_eligible_records_in_batch_order():
    now = timezone.now()
    eligible_older, item, inventory = create_reserved_order(
        order_number="ELIGIBLE-OLDER",
        reserved_at=now - timedelta(minutes=40),
    )
    recent, recent_item, recent_inventory = create_reserved_order(
        order_number="RECENT",
        reserved_at=now - timedelta(minutes=5),
    )
    confirmed, confirmed_item, confirmed_inventory = create_reserved_order(
        order_number="CONFIRMED",
        reserved_at=now - timedelta(minutes=45),
        status=Order.Status.CONFIRMED,
        reserved_quantity=0,
    )
    eligible_newer, newer_item, newer_inventory = create_reserved_order(
        order_number="ELIGIBLE-NEWER",
        reserved_at=now - timedelta(minutes=35),
    )

    queryset_ids = list(expired_reserved_orders_queryset(now=now).values_list("id", flat=True))
    batch_ids = expired_reserved_order_ids(batch_size=1, now=now)

    assert queryset_ids == [eligible_older.id, eligible_newer.id]
    assert batch_ids == [eligible_older.id]


def test_no_expired_order_status_is_introduced():
    assert "expired" not in {choice[0] for choice in Order.Status.choices}
