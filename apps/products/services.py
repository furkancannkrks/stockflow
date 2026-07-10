from decimal import Decimal

from django.db import transaction

from apps.audit.models import AuditLog
from apps.audit.services import create_audit_log
from apps.products.models import Product


PRODUCT_UPDATE_FIELDS = {
    "name",
    "sku",
    "category",
    "unit_price",
    "low_stock_threshold",
    "is_active",
}


def update_product(product_id: int, updates: dict, performed_by) -> Product:
    unknown_fields = set(updates) - PRODUCT_UPDATE_FIELDS
    if unknown_fields:
        raise ValueError(f"Unsupported product update fields: {sorted(unknown_fields)}")

    with transaction.atomic():
        product = Product.objects.select_for_update().get(id=product_id)
        before = _product_snapshot(product)

        for field, value in updates.items():
            setattr(product, field, value)
        product.full_clean()
        product.save(update_fields=[*updates.keys(), "updated_at"])

        product.refresh_from_db()
        after = _product_snapshot(product)
        changes = {
            field: {"before": before[field], "after": after[field]}
            for field in sorted(PRODUCT_UPDATE_FIELDS)
            if before[field] != after[field]
        }

        if changes:
            create_audit_log(
                actor=performed_by,
                action=AuditLog.Action.PRODUCT_UPDATED,
                target=product,
                metadata={"changes": changes},
            )

        return product


def _product_snapshot(product: Product) -> dict:
    return {
        "name": product.name,
        "sku": product.sku,
        "category": product.category,
        "unit_price": _serialize_decimal(product.unit_price),
        "low_stock_threshold": product.low_stock_threshold,
        "is_active": product.is_active,
    }


def _serialize_decimal(value: Decimal) -> str:
    return str(value)
