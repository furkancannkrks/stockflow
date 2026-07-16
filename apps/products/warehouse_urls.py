from django.urls import path

from apps.products.browser_views import (
    WarehouseCreateView,
    WarehouseDetailView,
    WarehouseListView,
    WarehouseUpdateView,
)


app_name = "warehouses"

urlpatterns = [
    path("", WarehouseListView.as_view(), name="warehouse-list"),
    path("new/", WarehouseCreateView.as_view(), name="warehouse-create"),
    path("<int:pk>/", WarehouseDetailView.as_view(), name="warehouse-detail"),
    path("<int:pk>/edit/", WarehouseUpdateView.as_view(), name="warehouse-update"),
]
