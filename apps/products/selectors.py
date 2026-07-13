from django.db.models import Exists, OuterRef

from apps.inventory.models import Inventory
from apps.inventory.selectors import low_stock_inventory, out_of_stock_inventory


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
