from django.core.paginator import Paginator
from django.views.generic import TemplateView

from apps.audit.selectors import audit_log_list_queryset
from apps.users.permissions import ManagerRequiredMixin


AUDIT_LOGS_PER_PAGE = 25


class AuditLogListView(ManagerRequiredMixin, TemplateView):
    template_name = "audit/audit_log_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        paginator = Paginator(audit_log_list_queryset(), AUDIT_LOGS_PER_PAGE)
        context["page_obj"] = paginator.get_page(self.request.GET.get("page"))
        return context
