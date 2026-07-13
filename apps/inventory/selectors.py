from django.db.models import F

from apps.inventory.models import Inventory


def inventory_with_available_quantity(queryset=None):
    if queryset is None:
        queryset = Inventory.objects.all()
    return queryset.annotate(
        available_quantity_value=F("quantity") - F("reserved_quantity")
    )
