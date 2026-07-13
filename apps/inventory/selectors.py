from django.db.models import F, Q

from apps.inventory.models import Inventory, StockMovement


def inventory_with_available_quantity(queryset=None):
    if queryset is None:
        queryset = Inventory.objects.all()
    return queryset.annotate(
        available_quantity_value=F("quantity") - F("reserved_quantity")
    )


def low_stock_inventory(queryset=None):
    return inventory_with_available_quantity(queryset).filter(
        available_quantity_value__lte=F("product__low_stock_threshold")
    )


def out_of_stock_inventory(queryset=None):
    return inventory_with_available_quantity(queryset).filter(
        available_quantity_value__lte=0
    )


def inventory_list_queryset():
    return inventory_with_available_quantity().select_related("product", "warehouse")


def filter_inventory_rows(queryset, q="", warehouse_id=None, stock_status=""):
    if q:
        queryset = queryset.filter(
            Q(product__name__icontains=q)
            | Q(product__sku__icontains=q)
            | Q(warehouse__name__icontains=q)
            | Q(warehouse__code__icontains=q)
        )
    if warehouse_id:
        queryset = queryset.filter(warehouse_id=warehouse_id)
    if stock_status == "low_stock":
        queryset = low_stock_inventory(queryset)
    elif stock_status == "out_of_stock":
        queryset = out_of_stock_inventory(queryset)
    elif stock_status == "healthy":
        queryset = queryset.filter(
            available_quantity_value__gt=F("product__low_stock_threshold")
        )
    return queryset


def recent_movements_for_inventory(inventory_id, limit=20):
    return StockMovement.objects.filter(inventory_id=inventory_id).select_related(
        "created_by"
    )[:limit]
