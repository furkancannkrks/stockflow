from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.audit.services import create_audit_log
from apps.inventory.models import Inventory, StockMovement
from apps.orders.exceptions import (
    InactiveProduct,
    InactiveWarehouse,
    InvalidCancellationSource,
    InvalidInventoryState,
    InsufficientStock,
    InvalidOrderItemQuantity,
    InvalidOrderTransition,
    InventoryNotFound,
)
from apps.orders.models import Order, OrderItem

SUPPORTED_CANCELLATION_SOURCES = {"manual", "expiration"}


def reserve_order(order_id: int, performed_by) -> Order:
    with transaction.atomic():
        order = _get_locked_order_for_transition(order_id, Order.Status.DRAFT)

        items = _get_order_items(order)
        _validate_item_quantities(items)
        _validate_active_products(items)
        _validate_active_warehouses(items)

        inventory_keys = _inventory_keys_for_items(items)
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
        create_audit_log(
            actor=performed_by,
            action=AuditLog.Action.ORDER_RESERVED,
            target=order,
            metadata=_order_audit_metadata(
                order,
                items,
                status_before=Order.Status.DRAFT,
                status_after=Order.Status.RESERVED,
            ),
        )

        return order


def confirm_order(order_id: int, performed_by) -> Order:
    with transaction.atomic():
        order = _get_locked_order_for_transition(order_id, Order.Status.RESERVED)
        items = _get_order_items(order)
        _validate_item_quantities(items)

        inventory_keys = _inventory_keys_for_items(items)
        inventory_by_key = _lock_inventory_by_key(inventory_keys)
        _validate_inventory_exists(items, inventory_by_key)
        _validate_inventory_can_confirm(items, inventory_by_key)

        movements = []
        items_by_key = {(item.product_id, item.warehouse_id): item for item in items}
        for key in inventory_keys:
            item = items_by_key[key]
            inventory = inventory_by_key[key]
            inventory.quantity -= item.quantity
            inventory.reserved_quantity -= item.quantity
            inventory.save(update_fields=["quantity", "reserved_quantity", "updated_at"])
            movements.append(
                StockMovement(
                    inventory=inventory,
                    movement_type=StockMovement.MovementType.STOCK_OUT,
                    quantity=item.quantity,
                    reference_type="order",
                    reference_id=str(order.id),
                    description=f"Confirmed order {order.order_number}",
                    created_by=performed_by,
                )
            )

        StockMovement.objects.bulk_create(movements)

        order.status = Order.Status.CONFIRMED
        order.save(update_fields=["status", "updated_at"])
        create_audit_log(
            actor=performed_by,
            action=AuditLog.Action.ORDER_CONFIRMED,
            target=order,
            metadata=_order_audit_metadata(
                order,
                items,
                status_before=Order.Status.RESERVED,
                status_after=Order.Status.CONFIRMED,
            ),
        )
        return order


def cancel_order(
    order_id: int,
    performed_by,
    source: str = "manual",
    reason: str | None = None,
) -> Order:
    if source not in SUPPORTED_CANCELLATION_SOURCES:
        raise InvalidCancellationSource(
            details=[
                {
                    "source": source,
                    "supported_sources": sorted(SUPPORTED_CANCELLATION_SOURCES),
                }
            ]
        )

    with transaction.atomic():
        order = _get_locked_order_for_transition(order_id, Order.Status.RESERVED)
        items = _get_order_items(order)
        _validate_item_quantities(items)

        inventory_keys = _inventory_keys_for_items(items)
        inventory_by_key = _lock_inventory_by_key(inventory_keys)
        _validate_inventory_exists(items, inventory_by_key)
        _validate_inventory_can_release(items, inventory_by_key)

        movements = []
        items_by_key = {(item.product_id, item.warehouse_id): item for item in items}
        for key in inventory_keys:
            item = items_by_key[key]
            inventory = inventory_by_key[key]
            inventory.reserved_quantity -= item.quantity
            inventory.save(update_fields=["reserved_quantity", "updated_at"])
            movements.append(
                StockMovement(
                    inventory=inventory,
                    movement_type=StockMovement.MovementType.RESERVATION_RELEASE,
                    quantity=item.quantity,
                    reference_type="order",
                    reference_id=str(order.id),
                    description=_cancellation_description(order, source, reason),
                    created_by=performed_by,
                )
            )

        StockMovement.objects.bulk_create(movements)

        order.status = Order.Status.CANCELLED
        order.save(update_fields=["status", "updated_at"])
        create_audit_log(
            actor=performed_by,
            action=AuditLog.Action.ORDER_CANCELLED,
            target=order,
            metadata=_order_audit_metadata(
                order,
                items,
                status_before=Order.Status.RESERVED,
                status_after=Order.Status.CANCELLED,
                extra={
                    "source": source,
                    "reason": reason,
                },
            ),
        )
        return order


def ship_order(order_id: int, performed_by) -> Order:
    with transaction.atomic():
        order = _get_locked_order_for_transition(order_id, Order.Status.CONFIRMED)
        order.status = Order.Status.SHIPPED
        order.save(update_fields=["status", "updated_at"])
        return order


def _get_locked_order_for_transition(order_id: int, required_status: str) -> Order:
    order = Order.objects.select_for_update().get(id=order_id)
    if order.status != required_status:
        raise InvalidOrderTransition(
            details=[
                {
                    "order_id": order.id,
                    "order_number": order.order_number,
                    "current_status": order.status,
                    "required_status": required_status,
                }
            ]
        )
    return order


def _get_order_items(order: Order) -> list[OrderItem]:
    return list(
        OrderItem.objects.select_related("product", "warehouse")
        .filter(order=order)
        .order_by("product_id", "warehouse_id", "id")
    )


def _inventory_keys_for_items(items: list[OrderItem]) -> list[tuple[int, int]]:
    return sorted({(item.product_id, item.warehouse_id) for item in items})


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


def _validate_inventory_can_confirm(
    items: list[OrderItem],
    inventory_by_key: dict[tuple[int, int], Inventory],
) -> None:
    invalid_items = []
    for item in items:
        inventory = inventory_by_key[(item.product_id, item.warehouse_id)]
        if inventory.quantity < item.quantity or inventory.reserved_quantity < item.quantity:
            invalid_items.append(
                _inventory_state_detail(item, inventory, required_quantity=item.quantity)
            )

    if invalid_items:
        raise InvalidInventoryState(details=invalid_items)


def _validate_inventory_can_release(
    items: list[OrderItem],
    inventory_by_key: dict[tuple[int, int], Inventory],
) -> None:
    invalid_items = []
    for item in items:
        inventory = inventory_by_key[(item.product_id, item.warehouse_id)]
        if inventory.reserved_quantity < item.quantity:
            invalid_items.append(
                _inventory_state_detail(item, inventory, required_quantity=item.quantity)
            )

    if invalid_items:
        raise InvalidInventoryState(details=invalid_items)


def _inventory_state_detail(
    item: OrderItem,
    inventory: Inventory,
    required_quantity: int,
) -> dict:
    return {
        "order_item_id": item.id,
        "product_id": item.product_id,
        "product_sku": item.product.sku,
        "warehouse_id": item.warehouse_id,
        "warehouse_code": item.warehouse.code,
        "required_quantity": required_quantity,
        "quantity": inventory.quantity,
        "reserved_quantity": inventory.reserved_quantity,
    }


def _cancellation_description(order: Order, source: str, reason: str | None) -> str:
    description = f"Released reservation for order {order.order_number}; source={source}"
    if reason:
        description = f"{description}; reason={reason}"
    return description


def _order_audit_metadata(
    order: Order,
    items: list[OrderItem],
    *,
    status_before: str,
    status_after: str,
    extra: dict | None = None,
) -> dict:
    metadata = {
        "order": {
            "id": order.id,
            "order_number": order.order_number,
            "status": {
                "before": status_before,
                "after": status_after,
            },
            "total_amount": str(order.total_amount),
            "reserved_at": order.reserved_at.isoformat() if order.reserved_at else None,
        },
        "items": [
            {
                "id": item.id,
                "product_id": item.product_id,
                "product_sku": item.product.sku,
                "warehouse_id": item.warehouse_id,
                "warehouse_code": item.warehouse.code,
                "quantity": item.quantity,
                "unit_price": str(item.unit_price),
                "subtotal": str(item.subtotal),
            }
            for item in items
        ],
    }
    if extra:
        metadata.update(extra)
    return metadata
