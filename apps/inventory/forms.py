from django import forms

from apps.inventory.services import (
    ADJUSTMENT_MANUAL,
    ADJUSTMENT_STOCK_IN,
    ADJUSTMENT_STOCK_OUT,
)
from apps.products.models import Warehouse


class InventoryListFilterForm(forms.Form):
    q = forms.CharField(
        required=False,
        label="Search",
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Product or warehouse"}
        ),
    )
    warehouse = forms.ModelChoiceField(
        required=False,
        queryset=Warehouse.objects.none(),
        empty_label="All warehouses",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    stock_status = forms.ChoiceField(
        required=False,
        label="Stock status",
        choices=[
            ("", "All stock levels"),
            ("low_stock", "Low stock"),
            ("out_of_stock", "Out of stock"),
            ("healthy", "Above threshold"),
        ],
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["warehouse"].queryset = Warehouse.objects.order_by("name", "code")


class InventoryAdjustmentForm(forms.Form):
    adjustment_type = forms.ChoiceField(
        choices=[
            (ADJUSTMENT_STOCK_IN, "Stock in"),
            (ADJUSTMENT_STOCK_OUT, "Stock out"),
            (ADJUSTMENT_MANUAL, "Set physical quantity"),
        ],
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    quantity = forms.IntegerField(
        min_value=1,
        widget=forms.NumberInput(attrs={"class": "form-control", "min": "1"}),
    )
    description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}),
    )
