import json

from django import template


register = template.Library()


@register.simple_tag
def audit_metadata_summary(metadata):
    if not metadata:
        return []
    if isinstance(metadata, dict) and isinstance(metadata.get("order"), dict):
        return _order_summary(metadata)
    if (
        isinstance(metadata, dict)
        and isinstance(metadata.get("product"), dict)
        and isinstance(metadata.get("warehouse"), dict)
        and isinstance(metadata.get("quantity"), dict)
    ):
        return _inventory_summary(metadata)
    return _generic_summary(metadata)


@register.simple_tag
def operation_id_display(correlation_id):
    if not correlation_id:
        return {"label": "Not linked", "title": "", "is_empty": True}
    if correlation_id.startswith("seed:"):
        return {
            "label": "Seed data",
            "title": correlation_id,
            "is_empty": False,
        }
    return {
        "label": correlation_id,
        "title": correlation_id,
        "is_empty": False,
    }


@register.filter
def pretty_json(value):
    return json.dumps(
        value,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    )


def _order_summary(metadata):
    order = metadata["order"]
    summary = []
    status = order.get("status")
    transition = _transition(status)
    if transition:
        summary.append({"label": "Status", "value": transition})

    items = metadata.get("items")
    if isinstance(items, list):
        summary.append({"label": "Items", "value": str(len(items))})

    total_amount = order.get("total_amount")
    if total_amount not in (None, ""):
        summary.append({"label": "Total", "value": str(total_amount)})

    reason = metadata.get("reason")
    if reason:
        summary.append({"label": "Reason", "value": str(reason)})

    source = metadata.get("source")
    if source:
        summary.append(
            {
                "label": "Source",
                "value": _humanize_identifier(source),
            }
        )
    return summary or _generic_summary(metadata)


def _inventory_summary(metadata):
    summary = []
    product_sku = metadata["product"].get("sku")
    if product_sku:
        summary.append({"label": "Product", "value": str(product_sku)})

    warehouse_code = metadata["warehouse"].get("code")
    if warehouse_code:
        summary.append({"label": "Warehouse", "value": str(warehouse_code)})

    quantity_transition = _transition(metadata.get("quantity"))
    if quantity_transition:
        summary.append({"label": "Quantity", "value": quantity_transition})

    adjustment_type = metadata.get("adjustment_type")
    if adjustment_type:
        summary.append(
            {
                "label": "Adjustment",
                "value": _humanize_identifier(adjustment_type),
            }
        )

    description = metadata.get("description")
    if description:
        summary.append({"label": "Description", "value": str(description)})
    return summary or _generic_summary(metadata)


def _generic_summary(metadata):
    if isinstance(metadata, list):
        return [{"label": "Details", "value": _count_label(len(metadata), "item")}]
    if not isinstance(metadata, dict):
        return [{"label": "Details", "value": str(metadata)}]

    summary = []
    changes = metadata.get("changes")
    if isinstance(changes, dict):
        summary.append(
            {
                "label": "Changes",
                "value": _count_label(len(changes), "field"),
            }
        )

    for key, value in metadata.items():
        if key == "changes" or len(summary) >= 4:
            continue
        if isinstance(value, list):
            display_value = _count_label(len(value), "item")
        elif isinstance(value, dict):
            transition = _transition(value)
            display_value = transition or _count_label(len(value), "field")
        else:
            display_value = _display_value(value)
        summary.append(
            {
                "label": _humanize_identifier(key),
                "value": display_value,
            }
        )
    return summary


def _transition(value):
    if not isinstance(value, dict):
        return ""
    if "before" not in value or "after" not in value:
        return ""
    return f"{_display_value(value['before'])} → {_display_value(value['after'])}"


def _display_value(value):
    if value is None:
        return "Not set"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def _humanize_identifier(value):
    return str(value).replace("_", " ").strip().capitalize()


def _count_label(count, singular):
    suffix = singular if count == 1 else f"{singular}s"
    return f"{count} {suffix}"
