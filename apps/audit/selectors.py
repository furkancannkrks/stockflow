from apps.audit.models import AuditLog


def audit_log_list_queryset():
    return AuditLog.objects.select_related("actor").order_by("-created_at", "-id")
