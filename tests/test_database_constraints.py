from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from apps.inventory.models import Inventory
from apps.orders.models import Order, OrderItem
from apps.products.models import Product, Warehouse


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
