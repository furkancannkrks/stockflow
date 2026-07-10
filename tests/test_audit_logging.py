from decimal import Decimal

import pytest

from apps.audit.admin import AuditLogAdmin
from apps.audit.models import AuditLog
from apps.inventory.models import Inventory, StockMovement
from apps.inventory.services import adjust_inventory
from apps.orders.exceptions import InsufficientStock
from apps.orders.models import Order, OrderItem
from apps.orders.services import cancel_order, confirm_order, reserve_order
from apps.orders.tasks import expire_reserved_orders
from apps.products.models import Product, Warehouse
from apps.products.services import update_product
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


def create_order(order_number="ORD-1", status=Order.Status.DRAFT, reserved_at=None):
    return Order.objects.create(
        order_number=order_number,
        customer_name="Test Customer",
        customer_email="customer@example.com",
        status=status,
        reserved_at=reserved_at,
    )


def create_order_item(order, product, warehouse, quantity=2, unit_price="1.00"):
    return OrderItem.objects.create(
        order=order,
        product=product,
        warehouse=warehouse,
        quantity=quantity,
        unit_price=Decimal(unit_price),
        subtotal=Decimal("0.00"),
    )


def create_reserved_order(quantity=2, inventory_quantity=10, reserved_quantity=2):
    product = create_product()
    warehouse = create_warehouse()
    inventory = Inventory.objects.create(
        product=product,
        warehouse=warehouse,
        quantity=inventory_quantity,
        reserved_quantity=reserved_quantity,
    )
    order = create_order(status=Order.Status.RESERVED)
    item = create_order_item(order, product, warehouse, quantity=quantity, unit_price="10.00")
    order.total_amount = item.subtotal
    order.save(update_fields=["total_amount", "updated_at"])
    return order, item, inventory


def test_product_update_creates_one_audit_record_with_before_and_after_values():
    user = create_user()
    product = create_product(price="10.00")

    update_product(
        product.id,
        {
            "name": "Updated Product",
            "unit_price": Decimal("12.50"),
            "low_stock_threshold": 5,
        },
        user,
    )

    audit = AuditLog.objects.get()
    assert audit.actor == user
    assert audit.action == AuditLog.Action.PRODUCT_UPDATED
    assert audit.target_model == "Product"
    assert audit.target_object_id == str(product.id)
    assert audit.metadata["changes"]["name"] == {
        "before": "Product SKU-1",
        "after": "Updated Product",
    }
    assert audit.metadata["changes"]["unit_price"] == {
        "before": "10.00",
        "after": "12.50",
    }


def test_inventory_adjustment_creates_one_audit_record_with_quantity_metadata():
    user = create_user()
    product = create_product()
    warehouse = create_warehouse()
    inventory = Inventory.objects.create(
        product=product,
        warehouse=warehouse,
        quantity=10,
        reserved_quantity=3,
    )

    adjust_inventory(
        product.id,
        warehouse.id,
        "stock_in",
        4,
        "received goods",
        user,
    )

    audit = AuditLog.objects.get()
    assert audit.actor == user
    assert audit.action == AuditLog.Action.INVENTORY_ADJUSTED
    assert audit.target_model == "Inventory"
    assert audit.metadata["adjustment_type"] == "stock_in"
    assert audit.metadata["movement_quantity"] == 4
    assert audit.metadata["quantity"] == {"before": 10, "after": 14}
    assert audit.metadata["reserved_quantity"] == {"before": 3, "after": 3}


def test_reservation_creates_one_audit_record_with_order_summary():
    user = create_user()
    product = create_product(price="7.50")
    warehouse = create_warehouse()
    inventory = Inventory.objects.create(product=product, warehouse=warehouse, quantity=10)
    order = create_order()
    create_order_item(order, product, warehouse, quantity=2)

    reserve_order(order.id, user)

    audit = AuditLog.objects.get(action=AuditLog.Action.ORDER_RESERVED)
    assert audit.actor == user
    assert audit.target_object_id == str(order.id)
    assert audit.metadata["order"]["order_number"] == order.order_number
    assert audit.metadata["order"]["status"] == {
        "before": Order.Status.DRAFT,
        "after": Order.Status.RESERVED,
    }
    assert audit.metadata["items"][0]["product_sku"] == product.sku
    assert audit.metadata["items"][0]["quantity"] == 2


def test_cancellation_creates_one_audit_record_with_manual_source():
    user = create_user()
    order, item, inventory = create_reserved_order()

    cancel_order(order.id, user, reason="customer request")

    audit = AuditLog.objects.get()
    assert audit.actor == user
    assert audit.action == AuditLog.Action.ORDER_CANCELLED
    assert audit.metadata["source"] == "manual"
    assert audit.metadata["reason"] == "customer request"
    assert audit.metadata["order"]["status"]["after"] == Order.Status.CANCELLED


def test_expiration_cancellation_creates_one_audit_record_without_duplicates():
    from datetime import timedelta
    from django.utils import timezone

    user = create_user()
    order, item, inventory = create_reserved_order()
    order.reserved_at = timezone.now() - timedelta(minutes=31)
    order.save(update_fields=["reserved_at", "updated_at"])

    first = expire_reserved_orders.run()
    second = expire_reserved_orders.run()

    audit = AuditLog.objects.get()
    assert first == {"expired": 1, "skipped": 0}
    assert second == {"expired": 0, "skipped": 0}
    assert audit.actor is None
    assert audit.action == AuditLog.Action.ORDER_CANCELLED
    assert audit.metadata["source"] == "expiration"
    assert audit.metadata["reason"] == "Reservation expired after 30 minutes."


def test_confirmation_creates_one_audit_record_with_order_summary():
    user = create_user()
    order, item, inventory = create_reserved_order()

    confirm_order(order.id, user)

    audit = AuditLog.objects.get()
    assert audit.actor == user
    assert audit.action == AuditLog.Action.ORDER_CONFIRMED
    assert audit.metadata["order"]["status"] == {
        "before": Order.Status.RESERVED,
        "after": Order.Status.CONFIRMED,
    }
    assert audit.metadata["items"][0]["warehouse_code"] == inventory.warehouse.code


def test_failed_operation_creates_no_audit_record():
    user = create_user()
    product = create_product()
    warehouse = create_warehouse()
    Inventory.objects.create(
        product=product,
        warehouse=warehouse,
        quantity=1,
        reserved_quantity=0,
    )
    order = create_order()
    create_order_item(order, product, warehouse, quantity=2)

    with pytest.raises(InsufficientStock):
        reserve_order(order.id, user)

    assert AuditLog.objects.count() == 0


def test_rolled_back_operation_leaves_no_audit_record_or_domain_change(monkeypatch):
    user = create_user()
    product = create_product()
    warehouse = create_warehouse()
    inventory = Inventory.objects.create(product=product, warehouse=warehouse, quantity=10)

    def fail_create(**kwargs):
        raise RuntimeError("audit write failed")

    monkeypatch.setattr(AuditLog.objects, "create", fail_create)

    with pytest.raises(RuntimeError, match="audit write failed"):
        adjust_inventory(
            product.id,
            warehouse.id,
            "stock_in",
            5,
            "received goods",
            user,
        )

    inventory.refresh_from_db()
    assert inventory.quantity == 10
    assert StockMovement.objects.count() == 0
    assert AuditLog.objects.count() == 0


def test_audit_admin_is_read_only():
    admin_instance = AuditLogAdmin(AuditLog, None)

    assert admin_instance.has_add_permission(None) is False
    assert admin_instance.has_change_permission(None) is False
    assert admin_instance.has_delete_permission(None) is False
    assert "metadata" in admin_instance.readonly_fields
