"""Root URL configuration for StockFlow."""
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.reports.browser_views import DashboardView


def health_check(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.users.urls")),
    path("api/", include("apps.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("health/", health_check, name="health_check"),
    path("", DashboardView.as_view(), name="dashboard"),
]
