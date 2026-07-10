from decimal import Decimal

import pytest

from apps.inventory.models import Inventory, StockMovement
from apps.orders.exceptions import (
    InvalidCancellationSource,
    InvalidOrderTransition,
)
from apps.orders.models import Order, OrderItem
from apps.orders.services import cancel_order, confirm_order, ship_order
from apps.products.models import Product, Warehouse
from apps.users.models import User


pytestmark = pytest.mark.django_db


def create_user(username="manager"):
    return User.objects.create_user(
        username=username,
        password="test-password",
        role=User.Role.MANAGER,
    )


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


def create_order(order_number="ORD-1", status=Order.Status.RESERVED):
    return Order.objects.create(
        order_number=order_number,
        customer_name="Test Customer",
        customer_email="customer@example.com",
        status=status,
        total_amount=Decimal("20.00"),
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


def create_reserved_order(quantity=2, inventory_quantity=10, reserved_quantity=2):
    user = create_user()
    product = create_product()
    warehouse = create_warehouse()
    inventory = Inventory.objects.create(
        product=product,
        warehouse=warehouse,
        quantity=inventory_quantity,
        reserved_quantity=reserved_quantity,
    )
    order = create_order()
    item = create_order_item(order, product, warehouse, quantity=quantity)
    return user, order, item, inventory


def test_successful_confirmation_updates_status_inventory_and_movement():
    user, order, item, inventory = create_reserved_order(quantity=2)

    confirmed_order = confirm_order(order.id, user)

    confirmed_order.refresh_from_db()
    inventory.refresh_from_db()
    movement = StockMovement.objects.get()

    assert confirmed_order.status == Order.Status.CONFIRMED
    assert inventory.quantity == 8
    assert inventory.reserved_quantity == 0
    assert movement.movement_type == StockMovement.MovementType.STOCK_OUT
    assert movement.quantity == item.quantity
    assert movement.created_by == user


def test_successful_cancellation_releases_reservation_without_physical_stock_change():
    user, order, item, inventory = create_reserved_order(quantity=2)

    cancelled_order = cancel_order(order.id, user)

    cancelled_order.refresh_from_db()
    inventory.refresh_from_db()
    movement = StockMovement.objects.get()

    assert cancelled_order.status == Order.Status.CANCELLED
    assert inventory.quantity == 10
    assert inventory.reserved_quantity == 0
    assert movement.movement_type == StockMovement.MovementType.RESERVATION_RELEASE
    assert movement.quantity == item.quantity
    assert "source=manual" in movement.description


def test_successful_shipping_changes_status_only():
    user = create_user()
    product = create_product()
    warehouse = create_warehouse()
    inventory = Inventory.objects.create(product=product, warehouse=warehouse, quantity=8)
    order = create_order(status=Order.Status.CONFIRMED)
    create_order_item(order, product, warehouse, quantity=2)

    shipped_order = ship_order(order.id, user)

    shipped_order.refresh_from_db()
    inventory.refresh_from_db()
    assert shipped_order.status == Order.Status.SHIPPED
    assert inventory.quantity == 8
    assert inventory.reserved_quantity == 0
    assert StockMovement.objects.count() == 0


@pytest.mark.parametrize(
    ("service", "starting_status"),
    [
        (confirm_order, Order.Status.DRAFT),
        (confirm_order, Order.Status.CONFIRMED),
        (cancel_order, Order.Status.DRAFT),
        (cancel_order, Order.Status.CANCELLED),
        (ship_order, Order.Status.DRAFT),
        (ship_order, Order.Status.RESERVED),
    ],
)
def test_invalid_transitions_are_rejected(service, starting_status):
    user = create_user()
    order = create_order(status=starting_status)

    with pytest.raises(InvalidOrderTransition):
        service(order.id, user)


def test_confirmation_rolls_back_inventory_and_movements_when_movement_write_fails(monkeypatch):
    user, order, item, inventory = create_reserved_order(quantity=2)

    def fail_bulk_create(movements):
        raise RuntimeError("movement write failed")

    monkeypatch.setattr(StockMovement.objects, "bulk_create", fail_bulk_create)

    with pytest.raises(RuntimeError, match="movement write failed"):
        confirm_order(order.id, user)

    order.refresh_from_db()
    inventory.refresh_from_db()
    assert order.status == Order.Status.RESERVED
    assert inventory.quantity == 10
    assert inventory.reserved_quantity == 2
    assert StockMovement.objects.count() == 0


def test_cancellation_accepts_expiration_source_without_expired_status():
    user, order, item, inventory = create_reserved_order(quantity=2)

    cancelled_order = cancel_order(
        order.id,
        user,
        source="expiration",
        reason="reservation window elapsed",
    )

    cancelled_order.refresh_from_db()
    movement = StockMovement.objects.get()
    assert cancelled_order.status == Order.Status.CANCELLED
    assert cancelled_order.status != "expired"
    assert "source=expiration" in movement.description
    assert "reason=reservation window elapsed" in movement.description


def test_unsupported_cancellation_source_is_rejected():
    user, order, item, inventory = create_reserved_order(quantity=2)

    with pytest.raises(InvalidCancellationSource) as exc_info:
        cancel_order(order.id, user, source="system")

    assert exc_info.value.details == [
        {
            "source": "system",
            "supported_sources": ["expiration", "manual"],
        }
    ]


def test_manual_cancellation_reason_is_propagated_to_movement_description():
    user, order, item, inventory = create_reserved_order(quantity=2)

    cancel_order(order.id, user, reason="customer requested cancellation")

    movement = StockMovement.objects.get()
    assert "source=manual" in movement.description
    assert "reason=customer requested cancellation" in movement.description


def test_repeated_cancellation_is_rejected():
    user, order, item, inventory = create_reserved_order(quantity=2)

    cancel_order(order.id, user)

    with pytest.raises(InvalidOrderTransition):
        cancel_order(order.id, user)


def test_repeated_confirmation_is_rejected():
    user, order, item, inventory = create_reserved_order(quantity=2)

    confirm_order(order.id, user)

    with pytest.raises(InvalidOrderTransition):
        confirm_order(order.id, user)
