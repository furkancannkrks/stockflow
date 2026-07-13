from django.db.models import Exists, F, OuterRef

from apps.inventory.models import Inventory


def low_stock_inventory_for_product():
    return Inventory.objects.filter(product_id=OuterRef("pk")).annotate(
        available_quantity_value=F("quantity") - F("reserved_quantity")
    ).filter(available_quantity_value__lte=F("product__low_stock_threshold"))


def annotate_product_low_stock(queryset):
    return queryset.annotate(
        has_low_stock=Exists(low_stock_inventory_for_product())
    )
