from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.inventory.models import Inventory, StockMovement
from apps.orders.exceptions import (
    InactiveProduct,
    InactiveWarehouse,
    InsufficientStock,
    InvalidOrderItemQuantity,
    InvalidOrderTransition,
    InventoryNotFound,
)
from apps.orders.models import Order, OrderItem


def reserve_order(order_id: int, performed_by) -> Order:
    with transaction.atomic():
        order = Order.objects.select_for_update().get(id=order_id)
        if order.status != Order.Status.DRAFT:
            raise InvalidOrderTransition(
                details=[
                    {
                        "order_id": order.id,
                        "order_number": order.order_number,
                        "current_status": order.status,
                        "required_status": Order.Status.DRAFT,
                    }
                ]
            )

        items = list(
            OrderItem.objects.select_related("product", "warehouse")
            .filter(order=order)
            .order_by("product_id", "warehouse_id", "id")
        )
        _validate_item_quantities(items)
        _validate_active_products(items)
        _validate_active_warehouses(items)

        inventory_keys = sorted({(item.product_id, item.warehouse_id) for item in items})
        inventory_by_key = _lock_inventory_by_key(inventory_keys)

        _validate_inventory_exists(items, inventory_by_key)
        _validate_stock_available(items, inventory_by_key)

        total_amount = Decimal("0.00")
        movements = []

        items_by_key = {(item.product_id, item.warehouse_id): item for item in items}
        for key in inventory_keys:
            item = items_by_key[key]
            inventory = inventory_by_key[key]
            current_unit_price = item.product.unit_price
            subtotal = Decimal(item.quantity) * current_unit_price

            inventory.reserved_quantity += item.quantity
            inventory.save(update_fields=["reserved_quantity", "updated_at"])

            item.unit_price = current_unit_price
            item.subtotal = subtotal
            item.save(update_fields=["unit_price", "subtotal"])

            total_amount += subtotal
            movements.append(
                StockMovement(
                    inventory=inventory,
                    movement_type=StockMovement.MovementType.RESERVATION,
                    quantity=item.quantity,
                    reference_type="order",
                    reference_id=str(order.id),
                    description=f"Reserved for order {order.order_number}",
                    created_by=performed_by,
                )
            )

        StockMovement.objects.bulk_create(movements)

        order.total_amount = total_amount
        order.reserved_at = timezone.now()
        order.status = Order.Status.RESERVED
        order.save(update_fields=["total_amount", "reserved_at", "status", "updated_at"])

        return order


def _lock_inventory_by_key(keys: list[tuple[int, int]]) -> dict[tuple[int, int], Inventory]:
    if not keys:
        return {}

    inventory_filter = Q()
    for product_id, warehouse_id in keys:
        inventory_filter |= Q(product_id=product_id, warehouse_id=warehouse_id)

    inventories = (
        Inventory.objects.select_for_update()
        .select_related("product", "warehouse")
        .filter(inventory_filter)
        .order_by("product_id", "warehouse_id")
    )
    return {(inventory.product_id, inventory.warehouse_id): inventory for inventory in inventories}


def _validate_item_quantities(items: list[OrderItem]) -> None:
    invalid_items = [
        {
            "order_item_id": item.id,
            "product_id": item.product_id,
            "warehouse_id": item.warehouse_id,
            "quantity": item.quantity,
        }
        for item in items
        if item.quantity <= 0
    ]
    if invalid_items:
        raise InvalidOrderItemQuantity(details=invalid_items)


def _validate_active_products(items: list[OrderItem]) -> None:
    inactive_items = [
        {
            "order_item_id": item.id,
            "product_id": item.product_id,
            "product_sku": item.product.sku,
        }
        for item in items
        if not item.product.is_active
    ]
    if inactive_items:
        raise InactiveProduct(details=inactive_items)


def _validate_active_warehouses(items: list[OrderItem]) -> None:
    inactive_items = [
        {
            "order_item_id": item.id,
            "warehouse_id": item.warehouse_id,
            "warehouse_code": item.warehouse.code,
        }
        for item in items
        if not item.warehouse.is_active
    ]
    if inactive_items:
        raise InactiveWarehouse(details=inactive_items)


def _validate_inventory_exists(
    items: list[OrderItem],
    inventory_by_key: dict[tuple[int, int], Inventory],
) -> None:
    missing_items = [
        {
            "order_item_id": item.id,
            "product_id": item.product_id,
            "product_sku": item.product.sku,
            "warehouse_id": item.warehouse_id,
            "warehouse_code": item.warehouse.code,
        }
        for item in items
        if (item.product_id, item.warehouse_id) not in inventory_by_key
    ]
    if missing_items:
        raise InventoryNotFound(details=missing_items)


def _validate_stock_available(
    items: list[OrderItem],
    inventory_by_key: dict[tuple[int, int], Inventory],
) -> None:
    insufficient_items = []
    for item in items:
        inventory = inventory_by_key[(item.product_id, item.warehouse_id)]
        available_quantity = inventory.available_quantity
        if item.quantity > available_quantity:
            insufficient_items.append(
                {
                    "order_item_id": item.id,
                    "product_id": item.product_id,
                    "product_sku": item.product.sku,
                    "warehouse_id": item.warehouse_id,
                    "warehouse_code": item.warehouse.code,
                    "requested_quantity": item.quantity,
                    "available_quantity": available_quantity,
                }
            )

    if insufficient_items:
        raise InsufficientStock(details=insufficient_items)
