from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.users.models import User


def is_manager(user) -> bool:
    return bool(
        user
        and user.is_authenticated
        and (user.is_superuser or user.role == User.Role.MANAGER)
    )


def is_stockflow_user(user) -> bool:
    return bool(
        user
        and user.is_authenticated
        and (
            user.is_superuser
            or user.role in {User.Role.MANAGER, User.Role.WAREHOUSE_STAFF}
        )
    )


class StockFlowRolePermission(BasePermission):
    message = "Your StockFlow role does not permit this action."

    def has_permission(self, request, view):
        return is_stockflow_user(request.user)


class ReadOnlyOrManagerPermission(StockFlowRolePermission):
    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        return request.method in SAFE_METHODS or is_manager(request.user)


class InventoryPermission(StockFlowRolePermission):
    """Both roles may read inventory and use the explicit adjustment action."""

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        if request.method in SAFE_METHODS or view.action == "adjustments":
            return True
        return is_manager(request.user)


class ManagerOnlyPermission(StockFlowRolePermission):
    def has_permission(self, request, view):
        return is_manager(request.user)


class StockFlowUserRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return is_stockflow_user(self.request.user)


class ManagerRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return is_manager(self.request.user)
