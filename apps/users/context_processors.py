from apps.users.permissions import is_manager, is_stockflow_user


def stockflow_permissions(request):
    return {
        "can_manage_catalog": is_manager(request.user),
        "can_manage_orders": is_manager(request.user),
        "can_adjust_inventory": is_stockflow_user(request.user),
        "can_export_reports": is_manager(request.user),
        "can_view_audit_logs": is_manager(request.user),
    }
