from django.db import models
from django.db.models import Q


class Product(models.Model):
    name = models.CharField(max_length=255)
    sku = models.CharField(max_length=64, unique=True)
    category = models.CharField(max_length=120, blank=True)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    low_stock_threshold = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "sku"]
        indexes = [
            models.Index(fields=["sku"], name="product_sku_idx"),
            models.Index(fields=["name"], name="product_name_idx"),
            models.Index(fields=["category"], name="product_category_idx"),
            models.Index(fields=["is_active"], name="product_is_active_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(unit_price__gt=0),
                name="product_unit_price_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.sku})"


class Warehouse(models.Model):
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=32, unique=True)
    address = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "code"]
        indexes = [
            models.Index(fields=["code"], name="warehouse_code_idx"),
            models.Index(fields=["name"], name="warehouse_name_idx"),
            models.Index(fields=["is_active"], name="warehouse_is_active_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"
