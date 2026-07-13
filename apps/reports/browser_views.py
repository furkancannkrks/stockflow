from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views.decorators.vary import vary_on_headers
from django.views.generic import TemplateView

from apps.htmx import is_htmx_request
from apps.reports.selectors import (
    dashboard_data,
    dashboard_recent_movements_data,
    dashboard_summary_data,
)
from apps.users.permissions import StockFlowUserRequiredMixin, is_manager


class DashboardView(StockFlowUserRequiredMixin, TemplateView):
    template_name = "reports/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(dashboard_data())
        context["can_export_reports"] = is_manager(self.request.user)
        return context


@method_decorator(vary_on_headers("HX-Request"), name="dispatch")
class DashboardPartialView(DashboardView):
    partial_template_name = ""

    def get_partial_context(self):
        raise NotImplementedError

    def get(self, request, *args, **kwargs):
        if not is_htmx_request(request):
            return super().get(request, *args, **kwargs)
        return render(request, self.partial_template_name, self.get_partial_context())


class DashboardSummaryView(DashboardPartialView):
    partial_template_name = "reports/partials/_summary_cards.html"

    def get_partial_context(self):
        return dashboard_summary_data()


class DashboardRecentMovementsView(DashboardPartialView):
    partial_template_name = "reports/partials/_recent_movements.html"

    def get_partial_context(self):
        return dashboard_recent_movements_data()
