from django.conf import settings
from django.db import models
from django.db.models import F, Q


class Inventory(models.Model):
    product = models.ForeignKey(
        "products.Product",
        on_delete=models.PROTECT,
        related_name="inventory_records",
    )
    warehouse = models.ForeignKey(
        "products.Warehouse",
        on_delete=models.PROTECT,
        related_name="inventory_records",
    )
    quantity = models.PositiveIntegerField(default=0)
    reserved_quantity = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["product__sku", "warehouse__code"]
        indexes = [
            models.Index(fields=["product"], name="inventory_product_idx"),
            models.Index(fields=["warehouse"], name="inventory_warehouse_idx"),
            models.Index(fields=["product", "warehouse"], name="inventory_product_wh_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "warehouse"],
                name="unique_inventory_product_warehouse",
            ),
            models.CheckConstraint(
                condition=Q(quantity__gte=0),
                name="inventory_quantity_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(reserved_quantity__gte=0),
                name="inventory_reserved_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(reserved_quantity__lte=F("quantity")),
                name="inventory_reserved_lte_quantity",
            ),
        ]

    @property
    def available_quantity(self) -> int:
        return self.quantity - self.reserved_quantity

    def __str__(self) -> str:
        return f"{self.product.sku} at {self.warehouse.code}"


class StockMovement(models.Model):
    class MovementType(models.TextChoices):
        ADJUSTMENT = "adjustment", "Adjustment"
        STOCK_IN = "stock_in", "Stock in"
        RESERVATION = "reservation", "Reservation"
        RESERVATION_RELEASE = "reservation_release", "Reservation release"
        STOCK_OUT = "stock_out", "Stock out"
        MANUAL_ADJUSTMENT = "manual_adjustment", "Manual adjustment"

    inventory = models.ForeignKey(
        Inventory,
        on_delete=models.PROTECT,
        related_name="stock_movements",
    )
    movement_type = models.CharField(max_length=32, choices=MovementType.choices)
    quantity = models.PositiveIntegerField()
    reference_type = models.CharField(max_length=64, blank=True)
    reference_id = models.CharField(max_length=64, blank=True)
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_movements",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["movement_type"], name="stock_move_type_idx"),
            models.Index(fields=["created_at"], name="stock_move_created_idx"),
            models.Index(
                fields=["reference_type", "reference_id"],
                name="stock_move_reference_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="stock_movement_quantity_positive",
            ),
            models.CheckConstraint(
                condition=Q(
                    movement_type__in=[
                        "adjustment",
                        "stock_in",
                        "reservation",
                        "reservation_release",
                        "stock_out",
                        "manual_adjustment",
                    ]
                ),
                name="stock_movement_type_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.movement_type} {self.quantity} for {self.inventory}"
