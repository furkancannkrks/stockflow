from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.inventory.models import Inventory, StockMovement
from apps.orders.models import Order, OrderItem
from apps.orders.selectors import expired_reserved_order_ids, expired_reserved_orders_queryset
from apps.orders.tasks import EXPIRATION_REASON, expire_reserved_orders
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

    result = expire_reserved_orders.run()

    order.refresh_from_db()
    inventory.refresh_from_db()
    movement = StockMovement.objects.get()

    assert result == {"expired": 1, "skipped": 0}
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

    result = expire_reserved_orders.run()

    order.refresh_from_db()
    inventory.refresh_from_db()
    assert result == {"expired": 0, "skipped": 0}
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

    result = expire_reserved_orders.run()

    order.refresh_from_db()
    assert result == {"expired": 0, "skipped": 0}
    assert order.status == Order.Status.CONFIRMED
    assert StockMovement.objects.count() == 0


def test_cancelled_order_does_not_expire_again():
    old_time = timezone.now() - timedelta(minutes=31)
    order, item, inventory = create_reserved_order(
        reserved_at=old_time,
        status=Order.Status.CANCELLED,
        reserved_quantity=0,
    )

    result = expire_reserved_orders.run()

    order.refresh_from_db()
    assert result == {"expired": 0, "skipped": 0}
    assert order.status == Order.Status.CANCELLED
    assert StockMovement.objects.count() == 0


def test_repeated_task_execution_does_not_release_twice_or_duplicate_movements():
    old_time = timezone.now() - timedelta(minutes=31)
    order, item, inventory = create_reserved_order(reserved_at=old_time)

    first_result = expire_reserved_orders.run()
    second_result = expire_reserved_orders.run()

    order.refresh_from_db()
    inventory.refresh_from_db()
    assert first_result == {"expired": 1, "skipped": 0}
    assert second_result == {"expired": 0, "skipped": 0}
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
        expire_reserved_orders.run()

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

    expire_reserved_orders.run(batch_size=1)

    order.refresh_from_db()
    inventory.refresh_from_db()
    movement = StockMovement.objects.get()
    assert order.status == Order.Status.CANCELLED
    assert inventory.reserved_quantity == 0
    assert movement.movement_type == StockMovement.MovementType.RESERVATION_RELEASE
    assert "source=expiration" in movement.description


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
