from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.vary import vary_on_headers
from django.views.generic import TemplateView

from apps.htmx import is_htmx_request
from apps.orders.exceptions import InsufficientStock, StockFlowDomainError
from apps.orders.forms import (
    CancelOrderForm,
    OrderForm,
    OrderItemFormSet,
    OrderListFilterForm,
)
from apps.orders.models import Order
from apps.orders.selectors import (
    filter_orders,
    order_detail_queryset,
    order_list_queryset,
)
from apps.orders.services import (
    cancel_order,
    confirm_order,
    reserve_order,
    save_draft_order,
    ship_order,
)
from apps.users.permissions import ManagerRequiredMixin, StockFlowUserRequiredMixin


ORDERS_PER_PAGE = 20


class OrderListView(StockFlowUserRequiredMixin, TemplateView):
    template_name = "orders/order_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = OrderListFilterForm(self.request.GET or None)
        queryset = order_list_queryset()
        if form.is_valid():
            queryset = filter_orders(queryset, **form.cleaned_data)
        paginator = Paginator(queryset, ORDERS_PER_PAGE)
        context.update(
            {
                "filter_form": form,
                "page_obj": paginator.get_page(self.request.GET.get("page")),
            }
        )
        return context


class OrderDetailView(StockFlowUserRequiredMixin, TemplateView):
    template_name = "orders/order_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "order": get_object_or_404(order_detail_queryset(), pk=kwargs["pk"]),
                "cancel_form": CancelOrderForm(),
            }
        )
        return context


class DraftOrderFormView(ManagerRequiredMixin, TemplateView):
    template_name = "orders/order_form.html"
    page_title = "Create order"
    submit_label = "Create order"

    def get_order(self):
        if not hasattr(self, "order"):
            self.order = Order()
        return self.order

    def get_forms(self, data=None):
        order = self.get_order()
        return (
            OrderForm(data=data, instance=order),
            OrderItemFormSet(data=data, instance=order, prefix="items"),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if "form" not in context or "formset" not in context:
            context["form"], context["formset"] = self.get_forms()
        context.update(
            {
                "order": self.get_order(),
                "page_title": self.page_title,
                "submit_label": self.submit_label,
            }
        )
        return context

    def post(self, request, *args, **kwargs):
        form, formset = self.get_forms(request.POST)
        if form.is_valid() and formset.is_valid():
            items = [
                {
                    "product": item_form.cleaned_data["product"],
                    "warehouse": item_form.cleaned_data["warehouse"],
                    "quantity": item_form.cleaned_data["quantity"],
                }
                for item_form in formset.forms
                if item_form.cleaned_data
                and not item_form.cleaned_data.get("DELETE")
            ]
            try:
                order = save_draft_order(
                    order_id=self.get_order().id or None,
                    updates=form.cleaned_data,
                    items=items,
                )
            except (StockFlowDomainError, ValidationError) as exc:
                form.add_error(None, getattr(exc, "message", str(exc)))
            else:
                messages.success(request, f"Order {order.order_number} was saved.")
                return redirect("orders:order-detail", pk=order.id)

        return self.render_to_response(
            self.get_context_data(form=form, formset=formset)
        )


class OrderCreateView(DraftOrderFormView):
    pass


class OrderUpdateView(DraftOrderFormView):
    page_title = "Update draft order"
    submit_label = "Save changes"

    def get_order(self):
        if not hasattr(self, "order"):
            self.order = get_object_or_404(Order, pk=self.kwargs["pk"])
            if self.order.status != Order.Status.DRAFT:
                raise PermissionDenied("Only draft orders may be edited.")
        return self.order


@method_decorator(vary_on_headers("HX-Request"), name="dispatch")
class OrderActionView(ManagerRequiredMixin, View):
    http_method_names = ["post"]
    success_message = "Order updated."

    def perform_action(self, order_id):
        raise NotImplementedError

    def render_htmx_result(self, order_id, **context):
        context.update(
            {
                "order": get_object_or_404(order_detail_queryset(), pk=order_id),
                "cancel_form": CancelOrderForm(),
            }
        )
        return render(
            self.request,
            "orders/partials/_status_result.html",
            context,
        )

    def post(self, request, pk):
        get_object_or_404(Order, pk=pk)
        action_errors = []
        try:
            order = self.perform_action(pk)
        except InsufficientStock as exc:
            action_errors.append(exc.message)
            for detail in exc.details:
                action_errors.append(
                    (
                        f"{detail['product_sku']} at {detail['warehouse_code']}: "
                        f"requested {detail['requested_quantity']}, "
                        f"available {detail['available_quantity']}."
                    ),
                )
        except StockFlowDomainError as exc:
            action_errors.append(exc.message)
        else:
            if is_htmx_request(request):
                return self.render_htmx_result(
                    order.id,
                    action_success=self.success_message,
                )
            messages.success(request, self.success_message)
            return redirect("orders:order-detail", pk=order.id)

        if is_htmx_request(request):
            return self.render_htmx_result(pk, action_errors=action_errors)
        for error in action_errors:
            messages.error(request, error)
        return redirect("orders:order-detail", pk=pk)


class ReserveOrderView(OrderActionView):
    success_message = "Order reserved successfully."

    def perform_action(self, order_id):
        return reserve_order(order_id, self.request.user)


class ConfirmOrderView(OrderActionView):
    success_message = "Order confirmed successfully."

    def perform_action(self, order_id):
        return confirm_order(order_id, self.request.user)


class CancelOrderView(OrderActionView):
    success_message = "Order cancelled successfully."

    def perform_action(self, order_id):
        form = CancelOrderForm(self.request.POST)
        if not form.is_valid():
            raise StockFlowDomainError("Cancellation reason is not valid.")
        return cancel_order(
            order_id,
            self.request.user,
            source="manual",
            reason=form.cleaned_data["reason"] or None,
        )


class ShipOrderView(OrderActionView):
    success_message = "Order shipped successfully."

    def perform_action(self, order_id):
        return ship_order(order_id, self.request.user)
