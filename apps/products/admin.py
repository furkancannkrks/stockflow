from django.contrib import admin

from apps.products.models import Product, Warehouse


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "sku",
        "category",
        "unit_price",
        "low_stock_threshold",
        "is_active",
        "updated_at",
    )
    list_filter = ("is_active", "category")
    search_fields = ("name", "sku", "category")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name", "code", "address")
    readonly_fields = ("created_at", "updated_at")
