from django.urls import path

from apps.inventory.browser_views import (
    InventoryAdjustmentView,
    InventoryDetailView,
    InventoryListView,
)


app_name = "inventory"

urlpatterns = [
    path("", InventoryListView.as_view(), name="inventory-list"),
    path("<int:pk>/", InventoryDetailView.as_view(), name="inventory-detail"),
    path(
        "<int:pk>/adjust/",
        InventoryAdjustmentView.as_view(),
        name="inventory-adjust",
    ),
]
