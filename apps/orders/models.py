from decimal import Decimal

from django.db import models
from django.db.models import Q


class Order(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        RESERVED = "reserved", "Reserved"
        CONFIRMED = "confirmed", "Confirmed"
        CANCELLED = "cancelled", "Cancelled"
        SHIPPED = "shipped", "Shipped"

    order_number = models.CharField(max_length=64, unique=True)
    customer_name = models.CharField(max_length=255)
    customer_email = models.EmailField()
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    reserved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["order_number"], name="order_number_idx"),
            models.Index(fields=["customer_email"], name="order_customer_email_idx"),
            models.Index(fields=["status"], name="order_status_idx"),
            models.Index(fields=["status", "reserved_at"], name="order_expiration_idx"),
            models.Index(fields=["created_at"], name="order_created_at_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(total_amount__gte=0),
                name="order_total_amount_nonnegative",
            ),
        ]

    def __str__(self) -> str:
        return self.order_number


class OrderItem(models.Model):
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items",
    )
    product = models.ForeignKey(
        "products.Product",
        on_delete=models.PROTECT,
        related_name="order_items",
    )
    warehouse = models.ForeignKey(
        "products.Warehouse",
        on_delete=models.PROTECT,
        related_name="order_items",
    )
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        indexes = [
            models.Index(fields=["order"], name="order_item_order_idx"),
            models.Index(fields=["product"], name="order_item_product_idx"),
            models.Index(fields=["warehouse"], name="order_item_warehouse_idx"),
            models.Index(
                fields=["order", "product", "warehouse"],
                name="order_item_order_prod_wh_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["order", "product", "warehouse"],
                name="unique_order_product_warehouse",
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="order_item_quantity_positive",
            ),
            models.CheckConstraint(
                condition=Q(unit_price__gt=0),
                name="order_item_unit_price_positive",
            ),
            models.CheckConstraint(
                condition=Q(subtotal__gte=0),
                name="order_item_subtotal_nonnegative",
            ),
        ]

    def save(self, *args, **kwargs):
        self.subtotal = Decimal(self.quantity) * self.unit_price
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.quantity} x {self.product.sku} for {self.order.order_number}"
