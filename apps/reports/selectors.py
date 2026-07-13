from datetime import datetime, time

from django.db.models import Count, Q
from django.utils import timezone

from apps.inventory.models import StockMovement
from apps.inventory.selectors import low_stock_inventory
from apps.orders.models import Order
from apps.products.models import Product, Warehouse
from apps.products.selectors import annotate_product_stock_status


DASHBOARD_LIST_LIMIT = 8


def dashboard_summary_data():
    product_counts = annotate_product_stock_status(Product.objects.all()).aggregate(
        total_products=Count("id"),
        low_stock_products=Count("id", filter=Q(has_low_stock=True)),
        out_of_stock_products=Count("id", filter=Q(has_out_of_stock=True)),
    )
    order_counts = Order.objects.aggregate(
        reserved_orders=Count("id", filter=Q(status=Order.Status.RESERVED)),
        confirmed_orders=Count("id", filter=Q(status=Order.Status.CONFIRMED)),
    )
    today_start = timezone.make_aware(
        datetime.combine(timezone.localdate(), time.min),
        timezone.get_current_timezone(),
    )

    return {
        **product_counts,
        "total_warehouses": Warehouse.objects.count(),
        **order_counts,
        "today_stock_movements": StockMovement.objects.filter(
            created_at__gte=today_start
        ).count(),
    }


def dashboard_recent_movements_data(list_limit=DASHBOARD_LIST_LIMIT):
    return {
        "recent_stock_movements": list(
            StockMovement.objects.select_related(
                "inventory__product",
                "inventory__warehouse",
                "created_by",
            )[:list_limit]
        ),
    }


def dashboard_list_data(list_limit=DASHBOARD_LIST_LIMIT):
    return {
        "low_stock_inventory": list(
            low_stock_inventory()
            .select_related("product", "warehouse")
            .order_by("available_quantity_value", "product__sku", "warehouse__code")[
                :list_limit
            ]
        ),
        "recent_orders": list(Order.objects.all()[:list_limit]),
    }


def dashboard_data(list_limit=DASHBOARD_LIST_LIMIT):
    return {
        **dashboard_summary_data(),
        **dashboard_recent_movements_data(list_limit),
        **dashboard_list_data(list_limit),
    }
