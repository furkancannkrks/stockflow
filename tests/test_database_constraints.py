from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from apps.audit.models import AuditLog
from apps.inventory.models import Inventory, StockMovement
from apps.orders.models import IdempotencyRecord, Order, OrderItem
from apps.products.models import Product, Warehouse
from apps.users.models import User


pytestmark = pytest.mark.django_db


def create_product(sku="SKU-1"):
    return Product.objects.create(
        name=f"Product {sku}",
        sku=sku,
        category="General",
        unit_price=Decimal("10.00"),
        low_stock_threshold=1,
    )


def create_warehouse(code="WH-1"):
    return Warehouse.objects.create(
        name=f"Warehouse {code}",
        code=code,
    )


def create_order(order_number="ORD-1"):
    return Order.objects.create(
        order_number=order_number,
        customer_name="Constraint Customer",
        customer_email="constraints@example.com",
    )


def create_user(username="constraint-user"):
    return User.objects.create_user(
        username=username,
        password="test-password",
    )


def test_product_sku_database_constraint_is_unique():
    create_product("DUPLICATE-SKU")

    with pytest.raises(IntegrityError), transaction.atomic():
        create_product("DUPLICATE-SKU")


def test_warehouse_code_database_constraint_is_unique():
    create_warehouse("DUPLICATE-WH")

    with pytest.raises(IntegrityError), transaction.atomic():
        create_warehouse("DUPLICATE-WH")


def test_inventory_product_warehouse_database_constraint_is_unique():
    product = create_product()
    warehouse = create_warehouse()
    Inventory.objects.create(product=product, warehouse=warehouse, quantity=10)

    with pytest.raises(IntegrityError), transaction.atomic():
        Inventory.objects.create(product=product, warehouse=warehouse, quantity=5)


@pytest.mark.parametrize(
    ("quantity", "reserved_quantity"),
    [
        (-1, 0),
        (1, -1),
    ],
)
def test_inventory_quantities_cannot_be_negative(quantity, reserved_quantity):
    product = create_product()
    warehouse = create_warehouse()

    with pytest.raises(IntegrityError), transaction.atomic():
        Inventory.objects.create(
            product=product,
            warehouse=warehouse,
            quantity=quantity,
            reserved_quantity=reserved_quantity,
        )


def test_inventory_reserved_quantity_cannot_exceed_quantity():
    product = create_product()
    warehouse = create_warehouse()

    with pytest.raises(IntegrityError), transaction.atomic():
        Inventory.objects.create(
            product=product,
            warehouse=warehouse,
            quantity=3,
            reserved_quantity=4,
        )


def test_order_item_product_warehouse_pair_is_unique_within_order():
    product = create_product()
    warehouse = create_warehouse()
    order = create_order()
    OrderItem.objects.create(
        order=order,
        product=product,
        warehouse=warehouse,
        quantity=1,
        unit_price=product.unit_price,
        subtotal=product.unit_price,
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        OrderItem.objects.create(
            order=order,
            product=product,
            warehouse=warehouse,
            quantity=2,
            unit_price=product.unit_price,
            subtotal=product.unit_price * 2,
        )


def test_order_status_database_constraint_rejects_invalid_value():
    with pytest.raises(IntegrityError), transaction.atomic():
        Order.objects.create(
            order_number="ORD-INVALID-STATUS",
            customer_name="Constraint Customer",
            customer_email="constraints@example.com",
            status="invalid",
        )


def test_stock_movement_type_database_constraint_rejects_invalid_value():
    inventory = Inventory.objects.create(
        product=create_product("MOVEMENT-CONSTRAINT"),
        warehouse=create_warehouse("MOVEMENT-WH"),
        quantity=10,
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        StockMovement.objects.create(
            inventory=inventory,
            movement_type="invalid",
            quantity=1,
        )


def test_idempotency_status_database_constraint_rejects_invalid_value():
    with pytest.raises(IntegrityError), transaction.atomic():
        IdempotencyRecord.objects.create(
            actor=create_user(),
            key="invalid-status-key",
            operation="reserve_order",
            order=create_order("ORD-IDEMPOTENCY-STATUS"),
            request_fingerprint="a" * 64,
            status="invalid",
        )


def test_audit_action_database_constraint_rejects_invalid_value():
    with pytest.raises(IntegrityError), transaction.atomic():
        AuditLog.objects.create(
            action="invalid",
            target_model="orders.order",
            target_object_id="1",
            target_repr="ORD-INVALID-AUDIT-ACTION",
        )
