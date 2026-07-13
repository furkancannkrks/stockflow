from django.db.models import Exists, F, IntegerField, OuterRef, Q, Sum, Value
from django.db.models.functions import Coalesce

from apps.inventory.models import Inventory, StockMovement
from apps.inventory.selectors import (
    inventory_with_available_quantity,
    low_stock_inventory,
    out_of_stock_inventory,
)
from apps.products.models import Product


def low_stock_inventory_for_product():
    return low_stock_inventory(
        Inventory.objects.filter(product_id=OuterRef("pk"))
    )


def annotate_product_low_stock(queryset):
    return queryset.annotate(
        has_low_stock=Exists(low_stock_inventory_for_product())
    )


def out_of_stock_inventory_for_product():
    return out_of_stock_inventory(
        Inventory.objects.filter(product_id=OuterRef("pk"))
    )


def annotate_product_stock_status(queryset):
    return annotate_product_low_stock(queryset).annotate(
        has_out_of_stock=Exists(out_of_stock_inventory_for_product())
    )


def product_list_queryset():
    return annotate_product_low_stock(Product.objects.all()).annotate(
        total_inventory=Coalesce(
            Sum("inventory_records__quantity"),
            Value(0),
            output_field=IntegerField(),
        ),
        total_reserved_inventory=Coalesce(
            Sum("inventory_records__reserved_quantity"),
            Value(0),
            output_field=IntegerField(),
        ),
        available_inventory=F("total_inventory") - F("total_reserved_inventory"),
    )


def search_products(queryset, value):
    if not value:
        return queryset
    return queryset.filter(Q(name__icontains=value) | Q(sku__icontains=value))


def filter_products_by_warehouse(queryset, warehouse_id):
    if not warehouse_id:
        return queryset
    warehouse_inventory = Inventory.objects.filter(
        product_id=OuterRef("pk"),
        warehouse_id=warehouse_id,
    )
    return queryset.annotate(
        has_inventory_in_warehouse=Exists(warehouse_inventory)
    ).filter(has_inventory_in_warehouse=True)


def filter_products_by_low_stock(queryset, value):
    if value is None:
        return queryset
    if "has_low_stock" not in queryset.query.annotations:
        queryset = annotate_product_low_stock(queryset)
    return queryset.filter(has_low_stock=value)


def inventory_for_product(product_id):
    return (
        inventory_with_available_quantity(
            Inventory.objects.filter(product_id=product_id)
        )
        .select_related("warehouse")
        .order_by("warehouse__name", "warehouse__code")
    )


def recent_movements_for_product(product_id, limit=12):
    return (
        StockMovement.objects.filter(inventory__product_id=product_id)
        .select_related("inventory__warehouse", "created_by")[:limit]
    )
