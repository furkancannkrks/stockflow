from django.urls import path

from apps.orders.browser_views import (
    CancelOrderView,
    ConfirmOrderView,
    OrderCreateView,
    OrderDetailView,
    OrderListView,
    OrderUpdateView,
    ReserveOrderView,
    ShipOrderView,
)


app_name = "orders"

urlpatterns = [
    path("", OrderListView.as_view(), name="order-list"),
    path("new/", OrderCreateView.as_view(), name="order-create"),
    path("<int:pk>/", OrderDetailView.as_view(), name="order-detail"),
    path("<int:pk>/edit/", OrderUpdateView.as_view(), name="order-update"),
    path("<int:pk>/reserve/", ReserveOrderView.as_view(), name="order-reserve"),
    path("<int:pk>/confirm/", ConfirmOrderView.as_view(), name="order-confirm"),
    path("<int:pk>/cancel/", CancelOrderView.as_view(), name="order-cancel"),
    path("<int:pk>/ship/", ShipOrderView.as_view(), name="order-ship"),
]
