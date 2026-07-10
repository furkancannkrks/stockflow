from django.db import transaction

from apps.audit.models import AuditLog
from apps.audit.services import create_audit_log
from apps.inventory.exceptions import (
    InactiveProduct,
    InactiveWarehouse,
    InvalidInventoryAdjustment,
    InventoryNotFound,
)
from apps.inventory.models import Inventory, StockMovement


ADJUSTMENT_STOCK_IN = "stock_in"
ADJUSTMENT_STOCK_OUT = "stock_out"
ADJUSTMENT_MANUAL = "manual_adjustment"
SUPPORTED_ADJUSTMENT_TYPES = {
    ADJUSTMENT_STOCK_IN,
    ADJUSTMENT_STOCK_OUT,
    ADJUSTMENT_MANUAL,
}


def adjust_inventory(
    product_id: int,
    warehouse_id: int,
    adjustment_type: str,
    quantity: int,
    description: str,
    performed_by,
) -> Inventory:
    _validate_adjustment_input(adjustment_type, quantity)

    with transaction.atomic():
        inventory = _get_locked_inventory(product_id, warehouse_id)
        _validate_active_inventory_entities(inventory)

        previous_quantity = inventory.quantity
        previous_reserved_quantity = inventory.reserved_quantity
        new_quantity, movement_quantity = _calculate_adjustment(inventory, adjustment_type, quantity)
        inventory.quantity = new_quantity
        inventory.save(update_fields=["quantity", "updated_at"])

        StockMovement.objects.create(
            inventory=inventory,
            movement_type=_movement_type_for_adjustment(adjustment_type),
            quantity=movement_quantity,
            reference_type="inventory_adjustment",
            reference_id=str(inventory.id),
            description=description or "",
            created_by=performed_by,
        )
        create_audit_log(
            actor=performed_by,
            action=AuditLog.Action.INVENTORY_ADJUSTED,
            target=inventory,
            metadata={
                "adjustment_type": adjustment_type,
                "description": description or "",
                "input_quantity": quantity,
                "movement_quantity": movement_quantity,
                "quantity": {
                    "before": previous_quantity,
                    "after": inventory.quantity,
                },
                "reserved_quantity": {
                    "before": previous_reserved_quantity,
                    "after": inventory.reserved_quantity,
                },
                "product": {
                    "id": inventory.product_id,
                    "sku": inventory.product.sku,
                },
                "warehouse": {
                    "id": inventory.warehouse_id,
                    "code": inventory.warehouse.code,
                },
            },
        )

        return inventory


def _validate_adjustment_input(adjustment_type: str, quantity: int) -> None:
    if adjustment_type not in SUPPORTED_ADJUSTMENT_TYPES:
        raise InvalidInventoryAdjustment(
            details=[
                {
                    "adjustment_type": adjustment_type,
                    "supported_adjustment_types": sorted(SUPPORTED_ADJUSTMENT_TYPES),
                }
            ]
        )

    if quantity <= 0:
        raise InvalidInventoryAdjustment(
            details=[
                {
                    "quantity": quantity,
                    "reason": "Quantity must be positive.",
                }
            ]
        )


def _get_locked_inventory(product_id: int, warehouse_id: int) -> Inventory:
    try:
        return (
            Inventory.objects.select_for_update()
            .select_related("product", "warehouse")
            .get(product_id=product_id, warehouse_id=warehouse_id)
        )
    except Inventory.DoesNotExist as exc:
        raise InventoryNotFound(
            details=[
                {
                    "product_id": product_id,
                    "warehouse_id": warehouse_id,
                }
            ]
        ) from exc


def _validate_active_inventory_entities(inventory: Inventory) -> None:
    if not inventory.product.is_active:
        raise InactiveProduct(
            details=[
                {
                    "product_id": inventory.product_id,
                    "product_sku": inventory.product.sku,
                }
            ]
        )

    if not inventory.warehouse.is_active:
        raise InactiveWarehouse(
            details=[
                {
                    "warehouse_id": inventory.warehouse_id,
                    "warehouse_code": inventory.warehouse.code,
                }
            ]
        )


def _calculate_adjustment(
    inventory: Inventory,
    adjustment_type: str,
    quantity: int,
) -> tuple[int, int]:
    if adjustment_type == ADJUSTMENT_STOCK_IN:
        return inventory.quantity + quantity, quantity

    if adjustment_type == ADJUSTMENT_STOCK_OUT:
        new_quantity = inventory.quantity - quantity
        _validate_reserved_stock_protected(inventory, new_quantity)
        return new_quantity, quantity

    new_quantity = quantity
    if new_quantity == inventory.quantity:
        raise InvalidInventoryAdjustment(
            details=[
                {
                    "quantity": quantity,
                    "reason": "Manual adjustment must change the physical quantity.",
                }
            ]
        )
    _validate_reserved_stock_protected(inventory, new_quantity)
    return new_quantity, abs(new_quantity - inventory.quantity)


def _validate_reserved_stock_protected(inventory: Inventory, new_quantity: int) -> None:
    if new_quantity < inventory.reserved_quantity:
        raise InvalidInventoryAdjustment(
            details=[
                {
                    "inventory_id": inventory.id,
                    "quantity": inventory.quantity,
                    "reserved_quantity": inventory.reserved_quantity,
                    "requested_quantity": new_quantity,
                    "reason": "Physical quantity cannot be less than reserved quantity.",
                }
            ]
        )


def _movement_type_for_adjustment(adjustment_type: str) -> str:
    if adjustment_type == ADJUSTMENT_STOCK_IN:
        return StockMovement.MovementType.STOCK_IN
    if adjustment_type == ADJUSTMENT_STOCK_OUT:
        return StockMovement.MovementType.STOCK_OUT
    return StockMovement.MovementType.MANUAL_ADJUSTMENT
