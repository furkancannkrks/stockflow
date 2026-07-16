from django.conf import settings
from django.db import models
from django.db.models import Q


class AuditLog(models.Model):
    class Action(models.TextChoices):
        PRODUCT_UPDATED = "product_updated", "Product updated"
        INVENTORY_ADJUSTED = "inventory_adjusted", "Inventory adjusted"
        ORDER_RESERVED = "order_reserved", "Order reserved"
        ORDER_CANCELLED = "order_cancelled", "Order cancelled"
        ORDER_CONFIRMED = "order_confirmed", "Order confirmed"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    action = models.CharField(max_length=64, choices=Action.choices)
    target_model = models.CharField(max_length=100)
    target_object_id = models.CharField(max_length=64)
    target_repr = models.CharField(max_length=255)
    metadata = models.JSONField(default=dict, blank=True)
    correlation_id = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["action"], name="audit_action_idx"),
            models.Index(fields=["actor", "created_at"], name="audit_actor_created_idx"),
            models.Index(
                fields=["target_model", "target_object_id"],
                name="audit_target_idx",
            ),
            models.Index(fields=["correlation_id"], name="audit_correlation_idx"),
            models.Index(fields=["created_at"], name="audit_created_at_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(
                    action__in=[
                        "product_updated",
                        "inventory_adjusted",
                        "order_reserved",
                        "order_cancelled",
                        "order_confirmed",
                    ]
                ),
                name="audit_action_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.action} {self.target_model}:{self.target_object_id}"
