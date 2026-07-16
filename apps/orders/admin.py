from django.contrib import admin

from apps.orders.models import Order, OrderItem


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    fields = ("product", "warehouse", "quantity", "unit_price", "subtotal", "created_at")
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "order_number",
        "customer_name",
        "customer_email",
        "status",
        "total_amount",
        "reserved_at",
        "created_at",
    )
    list_filter = ("status", "reserved_at", "created_at")
    search_fields = ("order_number", "customer_name", "customer_email")
    readonly_fields = (
        "order_number",
        "customer_name",
        "customer_email",
        "status",
        "total_amount",
        "reserved_at",
        "created_at",
        "updated_at",
    )
    inlines = (OrderItemInline,)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ("order", "product", "warehouse", "quantity", "unit_price", "subtotal", "created_at")
    list_filter = ("warehouse", "product__category")
    search_fields = (
        "order__order_number",
        "product__name",
        "product__sku",
        "warehouse__name",
        "warehouse__code",
    )
    readonly_fields = (
        "order",
        "product",
        "warehouse",
        "quantity",
        "unit_price",
        "subtotal",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
