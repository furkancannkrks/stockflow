"""Root URL configuration for StockFlow."""
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.reports.browser_views import (
    DashboardRecentMovementsView,
    DashboardSummaryView,
    DashboardView,
)


def health_check(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.users.urls")),
    path("products/", include("apps.products.browser_urls", namespace="products")),
    path(
        "warehouses/",
        include("apps.products.warehouse_urls", namespace="warehouses"),
    ),
    path("inventory/", include("apps.inventory.browser_urls", namespace="inventory")),
    path(
        "stock-movements/",
        include("apps.inventory.movement_urls", namespace="stock-movements"),
    ),
    path("orders/", include("apps.orders.browser_urls", namespace="orders")),
    path("audit-logs/", include("apps.audit.browser_urls", namespace="audit-logs")),
    path("api/", include("apps.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("health/", health_check, name="health_check"),
    path(
        "dashboard/summary/",
        DashboardSummaryView.as_view(),
        name="dashboard-summary",
    ),
    path(
        "dashboard/recent-movements/",
        DashboardRecentMovementsView.as_view(),
        name="dashboard-recent-movements",
    ),
    path("", DashboardView.as_view(), name="dashboard"),
]
