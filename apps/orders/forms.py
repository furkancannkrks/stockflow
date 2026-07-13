from django import forms
from django.forms import BaseInlineFormSet, inlineformset_factory

from apps.orders.models import Order, OrderItem


class OrderForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ["order_number", "customer_name", "customer_email"]
        widgets = {
            "order_number": forms.TextInput(attrs={"class": "form-control"}),
            "customer_name": forms.TextInput(attrs={"class": "form-control"}),
            "customer_email": forms.EmailInput(attrs={"class": "form-control"}),
        }


class OrderItemForm(forms.ModelForm):
    class Meta:
        model = OrderItem
        fields = ["product", "warehouse", "quantity"]
        widgets = {
            "product": forms.Select(attrs={"class": "form-select"}),
            "warehouse": forms.Select(attrs={"class": "form-select"}),
            "quantity": forms.NumberInput(attrs={"class": "form-control", "min": "1"}),
        }


class BaseOrderItemFormSet(BaseInlineFormSet):
    def clean(self):
        if any(self.errors):
            return

        seen = set()
        duplicates = []
        for form in self.forms:
            if not form.cleaned_data or form.cleaned_data.get("DELETE"):
                continue
            product = form.cleaned_data.get("product")
            warehouse = form.cleaned_data.get("warehouse")
            if product is None or warehouse is None:
                continue
            key = (product.id, warehouse.id)
            if key in seen:
                duplicates.append(f"{product.sku} at {warehouse.code}")
            seen.add(key)

        if duplicates:
            raise forms.ValidationError(
                "Duplicate product and warehouse combinations: "
                + ", ".join(duplicates)
            )
        super().clean()


OrderItemFormSet = inlineformset_factory(
    Order,
    OrderItem,
    form=OrderItemForm,
    formset=BaseOrderItemFormSet,
    fields=["product", "warehouse", "quantity"],
    extra=1,
    can_delete=True,
    min_num=1,
    validate_min=True,
)


class OrderListFilterForm(forms.Form):
    q = forms.CharField(
        required=False,
        label="Search",
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Email or order number"}
        ),
    )
    status = forms.ChoiceField(
        required=False,
        choices=[("", "All statuses"), *Order.Status.choices],
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    created_after = forms.DateField(
        required=False,
        label="Created from",
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    created_before = forms.DateField(
        required=False,
        label="Created to",
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get("created_after")
        end = cleaned_data.get("created_before")
        if start and end and start > end:
            raise forms.ValidationError("Created from must be on or before created to.")
        return cleaned_data


class CancelOrderForm(forms.Form):
    reason = forms.CharField(
        required=False,
        max_length=500,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Cancellation reason"}
        ),
    )
