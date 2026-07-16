from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import FormView, TemplateView

from apps.products.forms import ProductForm, ProductListFilterForm, WarehouseForm
from apps.products.models import Warehouse
from apps.products.selectors import (
    filter_products_by_low_stock,
    filter_products_by_warehouse,
    inventory_for_product,
    product_list_queryset,
    recent_movements_for_product,
    search_products,
    warehouse_list_queryset,
)
from apps.products.services import update_product
from apps.users.permissions import ManagerRequiredMixin, StockFlowUserRequiredMixin


PRODUCTS_PER_PAGE = 20
WAREHOUSES_PER_PAGE = 25


class ProductListView(StockFlowUserRequiredMixin, TemplateView):
    template_name = "products/product_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = ProductListFilterForm(self.request.GET or None)
        queryset = product_list_queryset()

        if form.is_valid():
            data = form.cleaned_data
            queryset = search_products(queryset, data["q"])
            if data["category"]:
                queryset = queryset.filter(category__iexact=data["category"])
            if data["is_active"]:
                queryset = queryset.filter(is_active=data["is_active"] == "true")
            if data["warehouse"]:
                queryset = filter_products_by_warehouse(
                    queryset,
                    data["warehouse"].id,
                )
            if data["low_stock"]:
                queryset = filter_products_by_low_stock(
                    queryset,
                    data["low_stock"] == "true",
                )

        paginator = Paginator(queryset.order_by("name", "sku"), PRODUCTS_PER_PAGE)
        context.update(
            {
                "filter_form": form,
                "page_obj": paginator.get_page(self.request.GET.get("page")),
            }
        )
        return context


class ProductDetailView(StockFlowUserRequiredMixin, TemplateView):
    template_name = "products/product_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        product = get_object_or_404(product_list_queryset(), pk=kwargs["pk"])
        context.update(
            {
                "product": product,
                "inventory_rows": list(inventory_for_product(product.id)),
                "recent_movements": list(recent_movements_for_product(product.id)),
            }
        )
        return context


class ProductCreateView(ManagerRequiredMixin, FormView):
    template_name = "products/product_form.html"
    form_class = ProductForm

    def form_valid(self, form):
        product = form.save()
        messages.success(self.request, f"Product {product.sku} was created.")
        return redirect("products:product-detail", pk=product.id)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Create product"
        context["submit_label"] = "Create product"
        return context


class ProductUpdateView(ManagerRequiredMixin, FormView):
    template_name = "products/product_form.html"
    form_class = ProductForm

    def get_product(self):
        if not hasattr(self, "product"):
            self.product = get_object_or_404(
                product_list_queryset(),
                pk=self.kwargs["pk"],
            )
        return self.product

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self.get_product()
        return kwargs

    def form_valid(self, form):
        try:
            product = update_product(
                self.get_product().id,
                form.cleaned_data,
                self.request.user,
            )
        except ValidationError as exc:
            form.add_error(None, exc)
            return self.form_invalid(form)

        messages.success(self.request, f"Product {product.sku} was updated.")
        return redirect("products:product-detail", pk=product.id)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Update product",
                "submit_label": "Save changes",
                "product": self.get_product(),
            }
        )
        return context


class WarehouseListView(StockFlowUserRequiredMixin, TemplateView):
    template_name = "warehouses/warehouse_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        paginator = Paginator(warehouse_list_queryset(), WAREHOUSES_PER_PAGE)
        context["page_obj"] = paginator.get_page(self.request.GET.get("page"))
        return context


class WarehouseDetailView(StockFlowUserRequiredMixin, TemplateView):
    template_name = "warehouses/warehouse_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["warehouse"] = get_object_or_404(
            warehouse_list_queryset(),
            pk=kwargs["pk"],
        )
        return context


class WarehouseCreateView(ManagerRequiredMixin, FormView):
    template_name = "warehouses/warehouse_form.html"
    form_class = WarehouseForm

    def form_valid(self, form):
        warehouse = form.save()
        messages.success(self.request, f"Warehouse {warehouse.code} was created.")
        return redirect("warehouses:warehouse-detail", pk=warehouse.id)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Create warehouse",
                "submit_label": "Create warehouse",
            }
        )
        return context


class WarehouseUpdateView(ManagerRequiredMixin, FormView):
    template_name = "warehouses/warehouse_form.html"
    form_class = WarehouseForm

    def get_warehouse(self):
        if not hasattr(self, "warehouse"):
            self.warehouse = get_object_or_404(
                Warehouse.objects.all(),
                pk=self.kwargs["pk"],
            )
        return self.warehouse

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self.get_warehouse()
        return kwargs

    def form_valid(self, form):
        warehouse = form.save()
        messages.success(self.request, f"Warehouse {warehouse.code} was updated.")
        return redirect("warehouses:warehouse-detail", pk=warehouse.id)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Update warehouse",
                "submit_label": "Save changes",
                "warehouse": self.get_warehouse(),
            }
        )
        return context
