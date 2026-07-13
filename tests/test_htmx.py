from decimal import Decimal
from unittest.mock import patch

import pytest
from django.test import Client

from apps.inventory.models import Inventory, StockMovement
from apps.inventory.services import adjust_inventory
from apps.orders.models import Order, OrderItem
from apps.orders.services import reserve_order
from apps.products.models import Product, Warehouse
from apps.users.models import User


pytestmark = pytest.mark.django_db
HTMX_HEADERS = {"HTTP_HX_REQUEST": "true"}


def create_user(username="htmx-manager", role=User.Role.MANAGER):
    return User.objects.create_user(
        username=username,
        password="test-password",
        role=role,
    )


def create_inventory(quantity=10, reserved_quantity=0):
    product = Product.objects.create(
        name="HTMX Product",
        sku="HTMX-SKU",
        category="General",
        unit_price=Decimal("12.50"),
        low_stock_threshold=2,
    )
    warehouse = Warehouse.objects.create(name="HTMX Warehouse", code="HTMX-WH")
    inventory = Inventory.objects.create(
        product=product,
        warehouse=warehouse,
        quantity=quantity,
        reserved_quantity=reserved_quantity,
    )
    return product, warehouse, inventory


def create_draft_order(product, warehouse, quantity=2):
    order = Order.objects.create(
        order_number="HTMX-ORDER",
        customer_name="HTMX Customer",
        customer_email="htmx@example.com",
    )
    OrderItem.objects.create(
        order=order,
        product=product,
        warehouse=warehouse,
        quantity=quantity,
        unit_price=product.unit_price,
        subtotal=product.unit_price * quantity,
    )
    return order


def test_normal_stock_adjustment_still_redirects(client):
    user = create_user()
    _, _, inventory = create_inventory()
    client.force_login(user)

    response = client.post(
        f"/inventory/{inventory.id}/adjust/",
        {"adjustment_type": "stock_in", "quantity": 3, "description": "Delivery"},
    )

    inventory.refresh_from_db()
    assert response.status_code == 302
    assert response.url == f"/inventory/{inventory.id}/"
    assert inventory.quantity == 13


def test_htmx_adjustment_returns_partial_and_refreshes_inventory(client):
    user = create_user()
    _, _, inventory = create_inventory()
    client.force_login(user)

    response = client.post(
        f"/inventory/{inventory.id}/adjust/",
        {"adjustment_type": "stock_in", "quantity": 3, "description": "Delivery"},
        **HTMX_HEADERS,
    )

    inventory.refresh_from_db()
    content = response.content.decode()
    template_names = [template.name for template in response.templates]
    assert response.status_code == 200
    assert "inventory/partials/_adjustment_result.html" in template_names
    assert '<section id="inventory-adjustment-region"' in content
    assert 'id="inventory-summary"' in content
    assert 'id="inventory-recent-movements"' in content
    assert 'hx-swap-oob="outerHTML"' in content
    assert "Delivery" in content
    assert "<html" not in content
    assert inventory.quantity == 13
    assert StockMovement.objects.filter(inventory=inventory).count() == 1


def test_htmx_adjustment_validation_errors_return_form_partial(client):
    user = create_user()
    _, _, inventory = create_inventory()
    client.force_login(user)

    response = client.post(
        f"/inventory/{inventory.id}/adjust/",
        {"adjustment_type": "stock_in", "quantity": 0, "description": ""},
        **HTMX_HEADERS,
    )

    inventory.refresh_from_db()
    content = response.content.decode()
    assert response.status_code == 200
    assert "inventory/partials/_adjustment_form.html" in [
        template.name for template in response.templates
    ]
    assert "Ensure this value is greater than or equal to 1" in content
    assert "<html" not in content
    assert inventory.quantity == 10


def test_htmx_adjustment_domain_conflict_is_inline(client):
    user = create_user()
    _, _, inventory = create_inventory(quantity=5, reserved_quantity=4)
    client.force_login(user)

    response = client.post(
        f"/inventory/{inventory.id}/adjust/",
        {"adjustment_type": "stock_out", "quantity": 2, "description": ""},
        **HTMX_HEADERS,
    )

    inventory.refresh_from_db()
    content = response.content.decode()
    assert response.status_code == 200
    assert "Inventory adjustment is not valid" in content
    assert "Physical quantity cannot be less than reserved quantity" in content
    assert inventory.quantity == 5
    assert StockMovement.objects.filter(inventory=inventory).count() == 0


def test_dashboard_partial_requires_authentication(client):
    response = client.get("/dashboard/summary/", **HTMX_HEADERS)

    assert response.status_code == 302
    assert response.url == "/login/?next=/dashboard/summary/"


def test_dashboard_htmx_and_normal_requests_use_partial_and_full_page(client):
    user = create_user()
    client.force_login(user)

    partial = client.get("/dashboard/summary/", **HTMX_HEADERS)
    movements_partial = client.get(
        "/dashboard/recent-movements/",
        **HTMX_HEADERS,
    )
    full_page = client.get("/dashboard/summary/")

    assert partial.status_code == 200
    assert "reports/partials/_summary_cards.html" in [
        template.name for template in partial.templates
    ]
    assert "<html" not in partial.content.decode()
    assert movements_partial.status_code == 200
    assert "reports/partials/_recent_movements.html" in [
        template.name for template in movements_partial.templates
    ]
    assert "<html" not in movements_partial.content.decode()
    assert full_page.status_code == 200
    assert "reports/dashboard.html" in [
        template.name for template in full_page.templates
    ]
    assert "<html" in full_page.content.decode()


def test_htmx_order_action_updates_status_partial(client):
    user = create_user()
    product, warehouse, inventory = create_inventory()
    order = create_draft_order(product, warehouse)
    client.force_login(user)

    response = client.post(f"/orders/{order.id}/reserve/", **HTMX_HEADERS)

    order.refresh_from_db()
    inventory.refresh_from_db()
    content = response.content.decode()
    assert response.status_code == 200
    assert "orders/partials/_status_result.html" in [
        template.name for template in response.templates
    ]
    assert 'id="order-status-actions"' in content
    assert "Order reserved successfully" in content
    assert "Confirm" in content
    assert "Cancel" in content
    assert "<html" not in content
    assert order.status == Order.Status.RESERVED
    assert inventory.reserved_quantity == 2


def test_unauthorized_htmx_order_action_is_rejected(client):
    user = create_user("htmx-staff", User.Role.WAREHOUSE_STAFF)
    product, warehouse, _ = create_inventory()
    order = create_draft_order(product, warehouse)
    client.force_login(user)

    response = client.post(f"/orders/{order.id}/reserve/", **HTMX_HEADERS)

    order.refresh_from_db()
    assert response.status_code == 403
    assert order.status == Order.Status.DRAFT


def test_htmx_invalid_transition_is_not_bypassed(client):
    user = create_user()
    product, warehouse, inventory = create_inventory()
    order = create_draft_order(product, warehouse)
    client.force_login(user)

    response = client.post(f"/orders/{order.id}/confirm/", **HTMX_HEADERS)

    order.refresh_from_db()
    inventory.refresh_from_db()
    assert response.status_code == 200
    assert "The requested order transition is not allowed" in response.content.decode()
    assert order.status == Order.Status.DRAFT
    assert inventory.quantity == 10
    assert inventory.reserved_quantity == 0


def test_htmx_insufficient_stock_conflict_is_inline(client):
    user = create_user()
    product, warehouse, inventory = create_inventory(quantity=3, reserved_quantity=1)
    order = create_draft_order(product, warehouse, quantity=4)
    client.force_login(user)

    response = client.post(f"/orders/{order.id}/reserve/", **HTMX_HEADERS)

    order.refresh_from_db()
    inventory.refresh_from_db()
    content = response.content.decode()
    assert response.status_code == 200
    assert "One or more order items do not have enough available stock" in content
    assert "HTMX-SKU at HTMX-WH: requested 4, available 2" in content
    assert order.status == Order.Status.DRAFT
    assert inventory.reserved_quantity == 1


def test_htmx_posts_still_require_csrf():
    user = create_user()
    product, warehouse, inventory = create_inventory()
    order = create_draft_order(product, warehouse)
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(user)

    adjustment_response = csrf_client.post(
        f"/inventory/{inventory.id}/adjust/",
        {"adjustment_type": "stock_in", "quantity": 1, "description": ""},
        **HTMX_HEADERS,
    )
    order_response = csrf_client.post(
        f"/orders/{order.id}/reserve/",
        **HTMX_HEADERS,
    )

    inventory.refresh_from_db()
    order.refresh_from_db()
    assert adjustment_response.status_code == 403
    assert order_response.status_code == 403
    assert inventory.quantity == 10
    assert inventory.reserved_quantity == 0
    assert order.status == Order.Status.DRAFT


def test_htmx_inventory_and_order_actions_call_services(client):
    user = create_user()
    product, warehouse, inventory = create_inventory()
    order = create_draft_order(product, warehouse)
    client.force_login(user)

    with patch(
        "apps.inventory.browser_views.adjust_inventory",
        wraps=adjust_inventory,
    ) as adjustment_service:
        client.post(
            f"/inventory/{inventory.id}/adjust/",
            {"adjustment_type": "stock_in", "quantity": 1, "description": ""},
            **HTMX_HEADERS,
        )

    with patch(
        "apps.orders.browser_views.reserve_order",
        wraps=reserve_order,
    ) as reservation_service:
        client.post(f"/orders/{order.id}/reserve/", **HTMX_HEADERS)

    adjustment_service.assert_called_once_with(
        product_id=product.id,
        warehouse_id=warehouse.id,
        adjustment_type="stock_in",
        quantity=1,
        description="",
        performed_by=user,
    )
    reservation_service.assert_called_once_with(order.id, user)
