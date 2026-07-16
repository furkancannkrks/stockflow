from django.urls import path

from apps.audit.browser_views import AuditLogListView


app_name = "audit-logs"

urlpatterns = [
    path("", AuditLogListView.as_view(), name="audit-log-list"),
]
