from django.views.generic import TemplateView

from apps.reports.selectors import dashboard_data
from apps.users.permissions import StockFlowUserRequiredMixin, is_manager


class DashboardView(StockFlowUserRequiredMixin, TemplateView):
    template_name = "reports/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(dashboard_data())
        context["can_export_reports"] = is_manager(self.request.user)
        return context
