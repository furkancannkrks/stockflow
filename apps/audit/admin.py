from django.contrib import admin

from apps.audit.models import AuditLog
from apps.users.permissions import is_manager


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_select_related = ("actor",)
    list_display = (
        "created_at",
        "action",
        "actor",
        "target_model",
        "target_object_id",
        "correlation_id",
    )
    list_filter = ("action", "target_model", "created_at")
    search_fields = (
        "actor__username",
        "action",
        "target_model",
        "target_object_id",
        "target_repr",
        "correlation_id",
    )
    readonly_fields = (
        "actor",
        "action",
        "target_model",
        "target_object_id",
        "target_repr",
        "metadata",
        "correlation_id",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_module_permission(self, request):
        return is_manager(request.user)

    def has_view_permission(self, request, obj=None):
        return is_manager(request.user)

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
