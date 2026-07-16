from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.inventory.models import Inventory, StockMovement
from apps.orders.models import Order
from apps.products.models import Product, Warehouse
from apps.reports.selectors import dashboard_data
from apps.users.models import User


pytestmark = pytest.mark.django_db


def create_user(username="dashboard-user", role=User.Role.MANAGER):
    return User.objects.create_user(
        username=username,
        password="test-password",
        role=role,
    )


def create_product(sku, threshold=2):
    return Product.objects.create(
        name=f"Product {sku}",
        sku=sku,
        category="General",
        unit_price=Decimal("10.00"),
        low_stock_threshold=threshold,
    )


def create_warehouse(code):
    return Warehouse.objects.create(name=f"Warehouse {code}", code=code)


def create_order(order_number, status):
    return Order.objects.create(
        order_number=order_number,
        customer_name=f"Customer {order_number}",
        customer_email=f"{order_number.lower()}@example.com",
        status=status,
    )


def test_dashboard_requires_authentication(client):
    response = client.get("/")

    assert response.status_code == 302
    assert response.url == "/login/?next=/"


def test_dashboard_counts_and_sections_are_correct(client):
    user = create_user()
    first_warehouse = create_warehouse("MAIN")
    second_warehouse = create_warehouse("SIDE")
    low_product = create_product("LOW", threshold=3)
    out_product = create_product("OUT", threshold=1)
    normal_product = create_product("NORMAL", threshold=2)
    low_inventory = Inventory.objects.create(
        product=low_product,
        warehouse=first_warehouse,
        quantity=5,
        reserved_quantity=3,
    )
    out_inventory = Inventory.objects.create(
        product=out_product,
        warehouse=second_warehouse,
        quantity=4,
        reserved_quantity=4,
    )
    Inventory.objects.create(
        product=normal_product,
        warehouse=first_warehouse,
        quantity=10,
        reserved_quantity=1,
    )
    today_movement = StockMovement.objects.create(
        inventory=low_inventory,
        movement_type=StockMovement.MovementType.STOCK_IN,
        quantity=2,
        created_by=user,
    )
    old_movement = StockMovement.objects.create(
        inventory=out_inventory,
        movement_type=StockMovement.MovementType.RESERVATION,
        quantity=1,
        created_by=user,
    )
    StockMovement.objects.filter(pk=old_movement.pk).update(
        created_at=timezone.now() - timedelta(days=2)
    )
    reserved_order = create_order("ORD-RESERVED", Order.Status.RESERVED)
    confirmed_order = create_order("ORD-CONFIRMED", Order.Status.CONFIRMED)
    create_order("ORD-DRAFT", Order.Status.DRAFT)
    client.force_login(user)

    response = client.get("/")

    assert response.status_code == 200
    assert response.context["total_products"] == 3
    assert response.context["total_warehouses"] == 2
    assert response.context["low_stock_products"] == 2
    assert response.context["out_of_stock_products"] == 1
    assert response.context["reserved_orders"] == 1
    assert response.context["confirmed_orders"] == 1
    assert response.context["today_stock_movements"] == 1
    assert response.context["recent_stock_movements"][0] == today_movement
    assert {inventory.id for inventory in response.context["low_stock_inventory"]} == {
        low_inventory.id,
        out_inventory.id,
    }
    assert {order.id for order in response.context["recent_orders"]} >= {
        reserved_order.id,
        confirmed_order.id,
    }


def test_dashboard_renders_base_navigation_and_sections(client):
    user = create_user()
    client.force_login(user)

    response = client.get("/")
    content = response.content.decode("utf-8")

    assert response.status_code == 200
    assert "Dashboard | StockFlow" in content
    for label in [
        "Dashboard",
        "Products",
        "Inventory",
        "Orders",
        "Warehouses",
        "Stock Movements",
        "Reports",
        "Audit Logs",
        "Logout",
        "Recent stock movements",
        "Low-stock products",
        "Recent orders",
    ]:
        assert label in content
    assert "/api/reports/low-stock.csv" in content
    assert 'hx-get="/dashboard/summary/"' in content
    assert 'hx-trigger="every 60s"' in content
    assert 'hx-get="/dashboard/recent-movements/"' in content
    assert 'hx-trigger="every 120s"' in content


def test_warehouse_staff_dashboard_hides_manager_only_navigation(client):
    user = create_user("dashboard-staff", User.Role.WAREHOUSE_STAFF)
    client.force_login(user)

    response = client.get("/")
    content = response.content.decode("utf-8")

    assert response.status_code == 200
    assert "Reports" not in content
    assert "Audit Logs" not in content
    assert "/api/reports/low-stock.csv" not in content
    assert response.context["can_export_reports"] is False
    assert response.context["can_view_audit_logs"] is False


def test_dashboard_query_count_does_not_grow_with_list_rows(
    client,
    django_assert_max_num_queries,
    django_assert_num_queries,
):
    user = create_user()
    warehouse = create_warehouse("QUERY")
    for index in range(12):
        product = create_product(f"QUERY-{index:02d}", threshold=3)
        inventory = Inventory.objects.create(
            product=product,
            warehouse=warehouse,
            quantity=5,
            reserved_quantity=3,
        )
        StockMovement.objects.create(
            inventory=inventory,
            movement_type=StockMovement.MovementType.STOCK_IN,
            quantity=1,
            created_by=user,
        )
        create_order(f"ORD-QUERY-{index:02d}", Order.Status.RESERVED)
    client.force_login(user)

    with django_assert_num_queries(7):
        data = dashboard_data()

    assert len(data["recent_stock_movements"]) == 8
    assert len(data["low_stock_inventory"]) == 8
    assert len(data["recent_orders"]) == 8

    with django_assert_max_num_queries(9):
        response = client.get("/")

    assert response.status_code == 200
    assert len(response.context["recent_stock_movements"]) == 8
    assert len(response.context["low_stock_inventory"]) == 8
    assert len(response.context["recent_orders"]) == 8
