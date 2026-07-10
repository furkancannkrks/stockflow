from decimal import Decimal

import pytest

from apps.inventory.exceptions import (
    InactiveProduct,
    InactiveWarehouse,
    InvalidInventoryAdjustment,
)
from apps.inventory.models import Inventory, StockMovement
from apps.inventory.services import adjust_inventory
from apps.products.models import Product, Warehouse
from apps.users.models import User


pytestmark = pytest.mark.django_db


def create_user(username="manager"):
    return User.objects.create_user(
        username=username,
        password="test-password",
        role=User.Role.MANAGER,
    )


def create_product(sku="SKU-1", is_active=True):
    return Product.objects.create(
        name=f"Product {sku}",
        sku=sku,
        category="General",
        unit_price=Decimal("10.00"),
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


def create_inventory(quantity=10, reserved_quantity=0, product=None, warehouse=None):
    product = product or create_product()
    warehouse = warehouse or create_warehouse()
    return Inventory.objects.create(
        product=product,
        warehouse=warehouse,
        quantity=quantity,
        reserved_quantity=reserved_quantity,
    )


def test_successful_stock_in_increases_quantity_and_creates_movement():
    user = create_user()
    inventory = create_inventory(quantity=10)

    adjusted = adjust_inventory(
        inventory.product_id,
        inventory.warehouse_id,
        "stock_in",
        5,
        "received goods",
        user,
    )

    adjusted.refresh_from_db()
    movement = StockMovement.objects.get()
    assert adjusted.quantity == 15
    assert adjusted.reserved_quantity == 0
    assert movement.movement_type == StockMovement.MovementType.STOCK_IN
    assert movement.quantity == 5
    assert movement.description == "received goods"
    assert movement.created_by == user


def test_successful_stock_out_decreases_quantity_and_preserves_reserved_quantity():
    user = create_user()
    inventory = create_inventory(quantity=10, reserved_quantity=3)

    adjusted = adjust_inventory(
        inventory.product_id,
        inventory.warehouse_id,
        "stock_out",
        4,
        "damaged goods",
        user,
    )

    adjusted.refresh_from_db()
    movement = StockMovement.objects.get()
    assert adjusted.quantity == 6
    assert adjusted.reserved_quantity == 3
    assert movement.movement_type == StockMovement.MovementType.STOCK_OUT
    assert movement.quantity == 4


def test_insufficient_removable_stock_is_rejected():
    user = create_user()
    inventory = create_inventory(quantity=10, reserved_quantity=7)

    with pytest.raises(InvalidInventoryAdjustment) as exc_info:
        adjust_inventory(
            inventory.product_id,
            inventory.warehouse_id,
            "stock_out",
            4,
            "too much",
            user,
        )

    inventory.refresh_from_db()
    assert inventory.quantity == 10
    assert inventory.reserved_quantity == 7
    assert exc_info.value.details[0]["reason"] == (
        "Physical quantity cannot be less than reserved quantity."
    )
    assert StockMovement.objects.count() == 0


@pytest.mark.parametrize("quantity", [0, -1])
def test_negative_or_zero_input_is_rejected(quantity):
    user = create_user()
    inventory = create_inventory()

    with pytest.raises(InvalidInventoryAdjustment):
        adjust_inventory(
            inventory.product_id,
            inventory.warehouse_id,
            "stock_in",
            quantity,
            "invalid",
            user,
        )

    inventory.refresh_from_db()
    assert inventory.quantity == 10
    assert StockMovement.objects.count() == 0


def test_manual_adjustment_sets_physical_quantity_and_protects_reserved_stock():
    user = create_user()
    inventory = create_inventory(quantity=10, reserved_quantity=4)

    adjusted = adjust_inventory(
        inventory.product_id,
        inventory.warehouse_id,
        "manual_adjustment",
        6,
        "cycle count",
        user,
    )

    adjusted.refresh_from_db()
    movement = StockMovement.objects.get()
    assert adjusted.quantity == 6
    assert adjusted.reserved_quantity == 4
    assert movement.movement_type == StockMovement.MovementType.MANUAL_ADJUSTMENT
    assert movement.quantity == 4


def test_manual_adjustment_below_reserved_stock_is_rejected():
    user = create_user()
    inventory = create_inventory(quantity=10, reserved_quantity=4)

    with pytest.raises(InvalidInventoryAdjustment):
        adjust_inventory(
            inventory.product_id,
            inventory.warehouse_id,
            "manual_adjustment",
            3,
            "bad count",
            user,
        )

    inventory.refresh_from_db()
    assert inventory.quantity == 10
    assert inventory.reserved_quantity == 4
    assert StockMovement.objects.count() == 0


def test_atomic_rollback_when_stock_movement_creation_fails(monkeypatch):
    user = create_user()
    inventory = create_inventory(quantity=10)

    def fail_create(**kwargs):
        raise RuntimeError("movement write failed")

    monkeypatch.setattr(StockMovement.objects, "create", fail_create)

    with pytest.raises(RuntimeError, match="movement write failed"):
        adjust_inventory(
            inventory.product_id,
            inventory.warehouse_id,
            "stock_in",
            5,
            "received goods",
            user,
        )

    inventory.refresh_from_db()
    assert inventory.quantity == 10
    assert StockMovement.objects.count() == 0


def test_inactive_product_is_rejected():
    user = create_user()
    product = create_product(is_active=False)
    warehouse = create_warehouse()
    inventory = create_inventory(product=product, warehouse=warehouse)

    with pytest.raises(InactiveProduct):
        adjust_inventory(
            inventory.product_id,
            inventory.warehouse_id,
            "stock_in",
            5,
            "received goods",
            user,
        )

    inventory.refresh_from_db()
    assert inventory.quantity == 10
    assert StockMovement.objects.count() == 0


def test_inactive_warehouse_is_rejected():
    user = create_user()
    product = create_product()
    warehouse = create_warehouse(is_active=False)
    inventory = create_inventory(product=product, warehouse=warehouse)

    with pytest.raises(InactiveWarehouse):
        adjust_inventory(
            inventory.product_id,
            inventory.warehouse_id,
            "stock_in",
            5,
            "received goods",
            user,
        )

    inventory.refresh_from_db()
    assert inventory.quantity == 10
    assert StockMovement.objects.count() == 0
