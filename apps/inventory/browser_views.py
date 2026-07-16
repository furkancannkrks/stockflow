from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.views.decorators.vary import vary_on_headers
from django.views.generic import FormView, TemplateView

from apps.htmx import is_htmx_request
from apps.inventory.exceptions import (
    InactiveProduct,
    InactiveWarehouse,
    InvalidInventoryAdjustment,
    InventoryNotFound,
)
from apps.inventory.forms import InventoryAdjustmentForm, InventoryListFilterForm
from apps.inventory.selectors import (
    filter_inventory_rows,
    inventory_list_queryset,
    recent_movements_for_inventory,
    stock_movement_list_queryset,
)
from apps.inventory.services import adjust_inventory
from apps.users.permissions import StockFlowUserRequiredMixin


INVENTORY_PER_PAGE = 25
STOCK_MOVEMENTS_PER_PAGE = 25
INVENTORY_ADJUSTMENT_ERRORS = (
    InactiveProduct,
    InactiveWarehouse,
    InvalidInventoryAdjustment,
    InventoryNotFound,
)


class InventoryListView(StockFlowUserRequiredMixin, TemplateView):
    template_name = "inventory/inventory_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = InventoryListFilterForm(self.request.GET or None)
        queryset = inventory_list_queryset()
        if form.is_valid():
            data = form.cleaned_data
            queryset = filter_inventory_rows(
                queryset,
                q=data["q"],
                warehouse_id=data["warehouse"].id if data["warehouse"] else None,
                stock_status=data["stock_status"],
            )

        paginator = Paginator(
            queryset.order_by("product__sku", "warehouse__code"),
            INVENTORY_PER_PAGE,
        )
        context.update(
            {
                "filter_form": form,
                "page_obj": paginator.get_page(self.request.GET.get("page")),
            }
        )
        return context


class InventoryDetailView(StockFlowUserRequiredMixin, TemplateView):
    template_name = "inventory/inventory_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        inventory = get_object_or_404(inventory_list_queryset(), pk=kwargs["pk"])
        context.update(
            {
                "inventory": inventory,
                "recent_movements": list(
                    recent_movements_for_inventory(inventory.id)
                ),
            }
        )
        return context


class StockMovementListView(StockFlowUserRequiredMixin, TemplateView):
    template_name = "inventory/stock_movement_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        paginator = Paginator(
            stock_movement_list_queryset(),
            STOCK_MOVEMENTS_PER_PAGE,
        )
        context["page_obj"] = paginator.get_page(self.request.GET.get("page"))
        return context


@method_decorator(vary_on_headers("HX-Request"), name="dispatch")
class InventoryAdjustmentView(StockFlowUserRequiredMixin, FormView):
    template_name = "inventory/inventory_adjustment_form.html"
    partial_template_name = "inventory/partials/_adjustment_form.html"
    form_class = InventoryAdjustmentForm

    def get_inventory(self):
        if not hasattr(self, "inventory"):
            self.inventory = get_object_or_404(
                inventory_list_queryset(),
                pk=self.kwargs["pk"],
            )
        return self.inventory

    def form_valid(self, form):
        inventory = self.get_inventory()
        try:
            adjusted = adjust_inventory(
                product_id=inventory.product_id,
                warehouse_id=inventory.warehouse_id,
                adjustment_type=form.cleaned_data["adjustment_type"],
                quantity=form.cleaned_data["quantity"],
                description=form.cleaned_data["description"],
                performed_by=self.request.user,
            )
        except INVENTORY_ADJUSTMENT_ERRORS as exc:
            form.add_error(None, exc.message)
            for detail in exc.details:
                if detail.get("reason"):
                    form.add_error(None, detail["reason"])
            return self.form_invalid(form)

        if is_htmx_request(self.request):
            self.inventory = get_object_or_404(
                inventory_list_queryset(),
                pk=adjusted.id,
            )
            context = self.get_context_data(
                form=self.get_form_class()(),
                adjustment_success=(
                    f"Inventory for {self.inventory.product.sku} was adjusted "
                    "successfully."
                ),
            )
            return render(
                self.request,
                "inventory/partials/_adjustment_result.html",
                context,
            )

        messages.success(
            self.request,
            f"Inventory for {adjusted.product.sku} was adjusted successfully.",
        )
        return redirect("inventory:inventory-detail", pk=adjusted.id)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        inventory = self.get_inventory()
        context.update(
            {
                "inventory": inventory,
                "recent_movements": list(
                    recent_movements_for_inventory(inventory.id)
                ),
            }
        )
        return context

    def render_to_response(self, context, **response_kwargs):
        if is_htmx_request(self.request):
            return render(self.request, self.partial_template_name, context)
        return super().render_to_response(context, **response_kwargs)
