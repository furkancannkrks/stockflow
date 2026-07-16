from django.urls import path

from apps.inventory.browser_views import StockMovementListView


app_name = "stock-movements"

urlpatterns = [
    path("", StockMovementListView.as_view(), name="stock-movement-list"),
]
