from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        MANAGER = "manager", "Manager"
        WAREHOUSE_STAFF = "warehouse_staff", "Warehouse staff"

    role = models.CharField(
        max_length=32,
        choices=Role.choices,
        default=Role.WAREHOUSE_STAFF,
    )

    def __str__(self) -> str:
        return self.get_username()
