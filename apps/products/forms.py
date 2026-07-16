from decimal import Decimal

from django import forms

from apps.products.models import Product, Warehouse


BOOLEAN_FILTER_CHOICES = [
    ("", "All"),
    ("true", "Yes"),
    ("false", "No"),
]


class ProductForm(forms.ModelForm):
    unit_price = forms.DecimalField(
        min_value=Decimal("0.01"),
        max_digits=12,
        decimal_places=2,
        widget=forms.NumberInput(
            attrs={"class": "form-control", "min": "0.01", "step": "0.01"}
        ),
    )

    class Meta:
        model = Product
        fields = [
            "name",
            "sku",
            "category",
            "unit_price",
            "low_stock_threshold",
            "is_active",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "sku": forms.TextInput(attrs={"class": "form-control"}),
            "category": forms.TextInput(attrs={"class": "form-control"}),
            "low_stock_threshold": forms.NumberInput(
                attrs={"class": "form-control", "min": "0"}
            ),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class WarehouseForm(forms.ModelForm):
    class Meta:
        model = Warehouse
        fields = ["name", "code", "address", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "code": forms.TextInput(attrs={"class": "form-control"}),
            "address": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class ProductListFilterForm(forms.Form):
    q = forms.CharField(
        required=False,
        label="Search",
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Name or SKU"}
        ),
    )
    category = forms.ChoiceField(
        required=False,
        choices=[("", "All categories")],
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    is_active = forms.ChoiceField(
        required=False,
        label="Active",
        choices=BOOLEAN_FILTER_CHOICES,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    warehouse = forms.ModelChoiceField(
        required=False,
        queryset=Warehouse.objects.none(),
        empty_label="All warehouses",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    low_stock = forms.ChoiceField(
        required=False,
        label="Low stock",
        choices=BOOLEAN_FILTER_CHOICES,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        categories = (
            Product.objects.exclude(category="")
            .order_by("category")
            .values_list("category", flat=True)
            .distinct()
        )
        self.fields["category"].choices = [
            ("", "All categories"),
            *((category, category) for category in categories),
        ]
        self.fields["warehouse"].queryset = Warehouse.objects.order_by("name", "code")
