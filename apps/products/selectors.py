from django.db.models import Exists, OuterRef

from apps.inventory.models import Inventory
from apps.inventory.selectors import low_stock_inventory


def low_stock_inventory_for_product():
    return low_stock_inventory(
        Inventory.objects.filter(product_id=OuterRef("pk"))
    )


def annotate_product_low_stock(queryset):
    return queryset.annotate(
        has_low_stock=Exists(low_stock_inventory_for_product())
    )
