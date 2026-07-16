from io import StringIO

import pytest
from django.core.management import call_command
from django.db.models import Count, F

from apps.audit.models import AuditLog
from apps.inventory.models import Inventory, StockMovement
from apps.orders.models import Order, OrderItem
from apps.orders.selectors import expired_reserved_order_ids
from apps.orders.services import cancel_order
from apps.products.management.commands.seed_data import (
    ORDER_DEFINITIONS,
    PRODUCT_DEFINITIONS,
    WAREHOUSE_DEFINITIONS,
)
from apps.products.models import Product, Warehouse
from apps.users.models import User


pytestmark = pytest.mark.django_db


def run_seed_command():
    output = StringIO()
    call_command("seed_data", stdout=output)
    return output.getvalue()


def test_seed_data_creates_required_dataset_and_scenarios(monkeypatch):
    monkeypatch.delenv("STOCKFLOW_DEMO_MANAGER_PASSWORD", raising=False)
    monkeypatch.delenv("STOCKFLOW_DEMO_STAFF_PASSWORD", raising=False)

    output = run_seed_command()

    assert Product.objects.count() == len(PRODUCT_DEFINITIONS)
    assert Warehouse.objects.count() == len(WAREHOUSE_DEFINITIONS)
    assert Inventory.objects.count() == 60
    assert Order.objects.count() == len(ORDER_DEFINITIONS)
    assert StockMovement.objects.count() >= 20
    assert not Inventory.objects.filter(reserved_quantity__gt=F("quantity")).exists()

    manager = User.objects.get(username="demo_manager")
    staff = User.objects.get(username="demo_warehouse_staff")
    assert manager.role == User.Role.MANAGER
    assert staff.role == User.Role.WAREHOUSE_STAFF
    assert manager.has_usable_password() is False
    assert staff.has_usable_password() is False

    mechanical = Inventory.objects.get(
        product__name="Mechanical Keyboard",
        warehouse__code="MAIN",
    )
    assert mechanical.quantity == 10
    assert mechanical.reserved_quantity == 8
    assert mechanical.available_quantity == 2

    usb_hub = Inventory.objects.get(
        product__name="USB-C Hub",
        warehouse__code="MAIN",
    )
    assert usb_hub.quantity == 20
    assert usb_hub.reserved_quantity == 5
    assert usb_hub.available_quantity == 15

    statuses = set(Order.objects.values_list("status", flat=True))
    assert statuses == set(Order.Status.values)

    insufficient = Order.objects.get(order_number="SEED-ORD-INSUFFICIENT")
    items = list(insufficient.items.select_related("product", "warehouse"))
    assert insufficient.status == Order.Status.DRAFT
    assert len(items) >= 2
    availability = {
        (inventory.product_id, inventory.warehouse_id): inventory.available_quantity
        for inventory in Inventory.objects.filter(
            product_id__in=[item.product_id for item in items],
            warehouse_id__in=[item.warehouse_id for item in items],
        )
    }
    insufficient_items = [
        item
        for item in items
        if item.quantity > availability[(item.product_id, item.warehouse_id)]
    ]
    assert [item.product.sku for item in insufficient_items] == ["MECH-KB-001"]

    cancellable = Order.objects.get(order_number="SEED-ORD-CANCEL")
    assert cancellable.status == Order.Status.RESERVED
    cancel_order(
        cancellable.id,
        performed_by=manager,
        source="manual",
        reason="Seed scenario verification.",
    )
    cancellable.refresh_from_db()
    assert cancellable.status == Order.Status.CANCELLED

    expired = Order.objects.get(order_number="SEED-ORD-EXPIRED")
    recent = Order.objects.get(order_number="SEED-ORD-RESERVED")
    eligible_ids = expired_reserved_order_ids()
    assert expired.status == Order.Status.RESERVED
    assert expired.id in eligible_ids
    assert recent.id not in eligible_ids

    audit_actions = set(AuditLog.objects.values_list("action", flat=True))
    assert {
        AuditLog.Action.INVENTORY_ADJUSTED,
        AuditLog.Action.ORDER_RESERVED,
        AuditLog.Action.ORDER_CONFIRMED,
        AuditLog.Action.ORDER_CANCELLED,
    }.issubset(audit_actions)

    assert "StockFlow seed data is ready." in output
    assert "Scenario A: Mechanical Keyboard @ MAIN" in output
    assert "Scenario E: SEED-ORD-EXPIRED" in output
    assert "demo_manager: unusable" in output
    assert "demo_warehouse_staff: unusable" in output


def test_seed_data_is_idempotent(monkeypatch):
    monkeypatch.delenv("STOCKFLOW_DEMO_MANAGER_PASSWORD", raising=False)
    monkeypatch.delenv("STOCKFLOW_DEMO_STAFF_PASSWORD", raising=False)

    run_seed_command()
    first_counts = {
        "users": User.objects.count(),
        "warehouses": Warehouse.objects.count(),
        "products": Product.objects.count(),
        "inventories": Inventory.objects.count(),
        "orders": Order.objects.count(),
        "order_items": OrderItem.objects.count(),
        "movements": StockMovement.objects.count(),
        "audit_logs": AuditLog.objects.count(),
    }

    second_output = run_seed_command()
    second_counts = {
        "users": User.objects.count(),
        "warehouses": Warehouse.objects.count(),
        "products": Product.objects.count(),
        "inventories": Inventory.objects.count(),
        "orders": Order.objects.count(),
        "order_items": OrderItem.objects.count(),
        "movements": StockMovement.objects.count(),
        "audit_logs": AuditLog.objects.count(),
    }

    assert second_counts == first_counts
    assert not (
        StockMovement.objects.values(
            "inventory_id",
            "movement_type",
            "reference_type",
            "reference_id",
        )
        .annotate(record_count=Count("id"))
        .filter(record_count__gt=1)
        .exists()
    )
    assert not (
        AuditLog.objects.exclude(correlation_id="")
        .values("correlation_id")
        .annotate(record_count=Count("id"))
        .filter(record_count__gt=1)
        .exists()
    )

    mechanical = Inventory.objects.get(
        product__sku="MECH-KB-001",
        warehouse__code="MAIN",
    )
    usb_hub = Inventory.objects.get(
        product__sku="USBC-HUB-001",
        warehouse__code="MAIN",
    )
    assert (mechanical.quantity, mechanical.reserved_quantity) == (10, 8)
    assert (usb_hub.quantity, usb_hub.reserved_quantity) == (20, 5)
    assert "Created this run: users=0, warehouses=0, products=0" in second_output
