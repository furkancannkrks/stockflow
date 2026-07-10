from decimal import Decimal

import pytest
from django.utils import timezone

from apps.inventory.models import Inventory, StockMovement
from apps.orders.exceptions import (
    InactiveProduct,
    InactiveWarehouse,
    InsufficientStock,
    InvalidOrderTransition,
    InventoryNotFound,
)
from apps.orders.models import Order, OrderItem
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


def create_product(sku="SKU-1", price="10.00", is_active=True):
    return Product.objects.create(
        name=f"Product {sku}",
        sku=sku,
        category="General",
        unit_price=Decimal(price),
        low_stock_threshold=1,
        is_active=is_active,
    )


def create_warehouse(code="WH-1", is_active=True):
    return Warehouse.objects.create(
        name=f"Warehouse {code}",
        code=code,
        address="Test address",
        is_active=is_active,
    )


def create_order(order_number="ORD-1", status=Order.Status.DRAFT):
    return Order.objects.create(
        order_number=order_number,
        customer_name="Test Customer",
        customer_email="customer@example.com",
        status=status,
    )


def create_order_item(order, product, warehouse, quantity=1, unit_price="1.00"):
    return OrderItem.objects.create(
        order=order,
        product=product,
        warehouse=warehouse,
        quantity=quantity,
        unit_price=Decimal(unit_price),
        subtotal=Decimal("0.00"),
    )


def test_successful_reservation_updates_order_items_inventory_and_movements():
    user = create_user()
    product = create_product(price="12.34")
    warehouse = create_warehouse()
    inventory = Inventory.objects.create(
        product=product,
        warehouse=warehouse,
        quantity=10,
        reserved_quantity=2,
    )
    order = create_order()
    item = create_order_item(order, product, warehouse, quantity=3, unit_price="1.00")

    reserved_order = reserve_order(order.id, user)

    inventory.refresh_from_db()
    item.refresh_from_db()
    reserved_order.refresh_from_db()

    assert reserved_order.status == Order.Status.RESERVED
    assert reserved_order.reserved_at is not None
    assert timezone.is_aware(reserved_order.reserved_at)
    assert reserved_order.total_amount == Decimal("37.02")
    assert item.unit_price == Decimal("12.34")
    assert item.subtotal == Decimal("37.02")
    assert inventory.quantity == 10
    assert inventory.reserved_quantity == 5
    assert inventory.available_quantity == 5

    movement = StockMovement.objects.get()
    assert movement.inventory == inventory
    assert movement.movement_type == StockMovement.MovementType.RESERVATION
    assert movement.quantity == 3
    assert movement.reference_type == "order"
    assert movement.reference_id == str(order.id)
    assert movement.created_by == user


def test_insufficient_stock_returns_conflict_details_and_changes_nothing():
    user = create_user()
    product = create_product()
    warehouse = create_warehouse()
    inventory = Inventory.objects.create(
        product=product,
        warehouse=warehouse,
        quantity=5,
        reserved_quantity=4,
    )
    order = create_order()
    create_order_item(order, product, warehouse, quantity=2)

    with pytest.raises(InsufficientStock) as exc_info:
        reserve_order(order.id, user)

    assert exc_info.value.details == [
        {
            "order_item_id": order.items.get().id,
            "product_id": product.id,
            "product_sku": product.sku,
            "warehouse_id": warehouse.id,
            "warehouse_code": warehouse.code,
            "requested_quantity": 2,
            "available_quantity": 1,
        }
    ]
    inventory.refresh_from_db()
    order.refresh_from_db()
    assert inventory.reserved_quantity == 4
    assert order.status == Order.Status.DRAFT
    assert order.reserved_at is None
    assert order.total_amount == Decimal("0.00")
    assert StockMovement.objects.count() == 0


def test_atomic_rollback_with_multiple_items_when_one_item_fails():
    user = create_user()
    product_1 = create_product(sku="SKU-1", price="5.00")
    product_2 = create_product(sku="SKU-2", price="7.00")
    warehouse = create_warehouse()
    inventory_1 = Inventory.objects.create(product=product_1, warehouse=warehouse, quantity=10)
    inventory_2 = Inventory.objects.create(product=product_2, warehouse=warehouse, quantity=1)
    order = create_order()
    item_1 = create_order_item(order, product_1, warehouse, quantity=3)
    item_2 = create_order_item(order, product_2, warehouse, quantity=2)

    with pytest.raises(InsufficientStock):
        reserve_order(order.id, user)

    inventory_1.refresh_from_db()
    inventory_2.refresh_from_db()
    item_1.refresh_from_db()
    item_2.refresh_from_db()
    order.refresh_from_db()

    assert inventory_1.reserved_quantity == 0
    assert inventory_2.reserved_quantity == 0
    assert item_1.unit_price == Decimal("1.00")
    assert item_2.unit_price == Decimal("1.00")
    assert order.status == Order.Status.DRAFT
    assert order.total_amount == Decimal("0.00")
    assert StockMovement.objects.count() == 0


def test_inactive_product_rejects_reservation():
    user = create_user()
    product = create_product(is_active=False)
    warehouse = create_warehouse()
    Inventory.objects.create(product=product, warehouse=warehouse, quantity=10)
    order = create_order()
    item = create_order_item(order, product, warehouse, quantity=1)

    with pytest.raises(InactiveProduct) as exc_info:
        reserve_order(order.id, user)

    assert exc_info.value.details[0]["order_item_id"] == item.id
    assert StockMovement.objects.count() == 0


def test_inactive_warehouse_rejects_reservation():
    user = create_user()
    product = create_product()
    warehouse = create_warehouse(is_active=False)
    Inventory.objects.create(product=product, warehouse=warehouse, quantity=10)
    order = create_order()
    item = create_order_item(order, product, warehouse, quantity=1)

    with pytest.raises(InactiveWarehouse) as exc_info:
        reserve_order(order.id, user)

    assert exc_info.value.details[0]["order_item_id"] == item.id
    assert StockMovement.objects.count() == 0


def test_invalid_order_status_rejects_reservation():
    user = create_user()
    order = create_order(status=Order.Status.CONFIRMED)

    with pytest.raises(InvalidOrderTransition) as exc_info:
        reserve_order(order.id, user)

    assert exc_info.value.details[0]["current_status"] == Order.Status.CONFIRMED


def test_missing_inventory_row_rejects_reservation():
    user = create_user()
    product = create_product()
    warehouse = create_warehouse()
    order = create_order()
    item = create_order_item(order, product, warehouse, quantity=1)

    with pytest.raises(InventoryNotFound) as exc_info:
        reserve_order(order.id, user)

    assert exc_info.value.details == [
        {
            "order_item_id": item.id,
            "product_id": product.id,
            "product_sku": product.sku,
            "warehouse_id": warehouse.id,
            "warehouse_code": warehouse.code,
        }
    ]
    assert StockMovement.objects.count() == 0


def test_inventory_locks_and_movements_follow_deterministic_key_order():
    user = create_user()
    warehouse = create_warehouse()
    product_1 = create_product(sku="SKU-1", price="2.00")
    product_2 = create_product(sku="SKU-2", price="3.00")
    inventory_1 = Inventory.objects.create(product=product_1, warehouse=warehouse, quantity=10)
    inventory_2 = Inventory.objects.create(product=product_2, warehouse=warehouse, quantity=10)
    order = create_order()
    create_order_item(order, product_2, warehouse, quantity=1)
    create_order_item(order, product_1, warehouse, quantity=1)

    reserve_order(order.id, user)

    movement_inventory_ids = list(
        StockMovement.objects.order_by("id").values_list("inventory_id", flat=True)
    )
    assert movement_inventory_ids == [inventory_1.id, inventory_2.id]
