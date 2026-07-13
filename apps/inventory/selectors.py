from django.db.models import F

from apps.inventory.models import Inventory


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
