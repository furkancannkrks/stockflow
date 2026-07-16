from django.contrib import admin

from apps.inventory.models import Inventory, StockMovement


@admin.register(Inventory)
class InventoryAdmin(admin.ModelAdmin):
    list_display = (
        "product",
        "warehouse",
        "quantity",
        "reserved_quantity",
        "available_quantity",
        "updated_at",
    )
    list_filter = ("warehouse", "product__category")
    search_fields = ("product__name", "product__sku", "warehouse__name", "warehouse__code")
    readonly_fields = ("available_quantity", "created_at", "updated_at")


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_select_related = ("inventory__product", "inventory__warehouse", "created_by")
    list_display = (
        "inventory",
        "movement_type",
        "quantity",
        "reference_type",
        "reference_id",
        "created_by",
        "created_at",
    )
    list_filter = ("movement_type", "created_at")
    search_fields = (
        "inventory__product__name",
        "inventory__product__sku",
        "inventory__warehouse__name",
        "inventory__warehouse__code",
        "reference_type",
        "reference_id",
        "description",
        "created_by__username",
    )
    readonly_fields = (
        "inventory",
        "movement_type",
        "quantity",
        "reference_type",
        "reference_id",
        "description",
        "created_by",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
