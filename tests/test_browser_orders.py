from datetime import timedelta
from decimal import Decimal

import pytest
from django.test import Client
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.inventory.models import Inventory, StockMovement
from apps.orders.forms import OrderItemForm, OrderItemFormSet
from apps.orders.models import Order, OrderItem
from apps.products.models import Product, Warehouse
from apps.users.models import User


pytestmark = pytest.mark.django_db


def create_user(username="order-manager", role=User.Role.MANAGER):
    return User.objects.create_user(
        username=username,
        password="test-password",
        role=role,
    )


def create_product(sku="SKU-1", price="10.00"):
    return Product.objects.create(
        name=f"Product {sku}",
        sku=sku,
        category="General",
        unit_price=Decimal(price),
        low_stock_threshold=2,
    )


def create_warehouse(code="WH-1"):
    return Warehouse.objects.create(name=f"Warehouse {code}", code=code)


def create_order(order_number="ORD-1", status=Order.Status.DRAFT, **overrides):
    values = {
        "order_number": order_number,
        "customer_name": "Test Customer",
        "customer_email": "customer@example.com",
        "status": status,
    }
    values.update(overrides)
    return Order.objects.create(**values)


def create_item(order, product, warehouse, quantity=1):
    return OrderItem.objects.create(
        order=order,
        product=product,
        warehouse=warehouse,
        quantity=quantity,
        unit_price=product.unit_price,
        subtotal=Decimal(quantity) * product.unit_price,
    )


def order_post_data(order_number="ORD-BROWSER", items=None, **overrides):
    items = items or []
    data = {
        "order_number": order_number,
        "customer_name": "Browser Customer",
        "customer_email": "browser@example.com",
        "items-TOTAL_FORMS": str(len(items)),
        "items-INITIAL_FORMS": "0",
        "items-MIN_NUM_FORMS": "1",
        "items-MAX_NUM_FORMS": "1000",
    }
    data.update(overrides)
    for index, item in enumerate(items):
        data[f"items-{index}-product"] = str(item["product"].id)
        data[f"items-{index}-warehouse"] = str(item["warehouse"].id)
        data[f"items-{index}-quantity"] = str(item["quantity"])
    return data


def test_order_item_form_never_accepts_prices():
    assert "unit_price" not in OrderItemForm.base_fields
    assert "subtotal" not in OrderItemForm.base_fields


def test_order_item_formset_rejects_duplicate_product_warehouse_pairs():
    product = create_product()
    warehouse = create_warehouse()
    data = order_post_data(
        items=[
            {"product": product, "warehouse": warehouse, "quantity": 1},
            {"product": product, "warehouse": warehouse, "quantity": 2},
        ]
    )

    formset = OrderItemFormSet(data=data, instance=Order(), prefix="items")

    assert formset.is_valid() is False
    assert "Duplicate product and warehouse" in str(formset.non_form_errors())


def test_manager_creates_multi_item_order_with_database_prices(client):
    user = create_user()
    first_product = create_product("SKU-1", "5.00")
    second_product = create_product("SKU-2", "7.50")
    warehouse = create_warehouse()
    client.force_login(user)
    data = order_post_data(
        items=[
            {"product": first_product, "warehouse": warehouse, "quantity": 2},
            {"product": second_product, "warehouse": warehouse, "quantity": 3},
        ]
    )
    data["items-0-unit_price"] = "0.01"
    data["items-0-subtotal"] = "0.02"

    response = client.post("/orders/new/", data)

    order = Order.objects.get(order_number="ORD-BROWSER")
    items = list(order.items.order_by("product__sku"))
    assert response.status_code == 302
    assert response.url == f"/orders/{order.id}/"
    assert order.status == Order.Status.DRAFT
    assert order.total_amount == Decimal("32.50")
    assert items[0].unit_price == Decimal("5.00")
    assert items[0].subtotal == Decimal("10.00")
    assert items[1].unit_price == Decimal("7.50")
    assert items[1].subtotal == Decimal("22.50")


def test_draft_order_update_replaces_items_and_recalculates_total(client):
    user = create_user()
    first_product = create_product("SKU-1", "5.00")
    second_product = create_product("SKU-2", "8.00")
    warehouse = create_warehouse()
    order = create_order()
    first_item = create_item(order, first_product, warehouse)
    second_item = create_item(order, second_product, warehouse)
    client.force_login(user)
    data = {
        "order_number": order.order_number,
        "customer_name": "Updated Customer",
        "customer_email": "updated@example.com",
        "items-TOTAL_FORMS": "2",
        "items-INITIAL_FORMS": "2",
        "items-MIN_NUM_FORMS": "1",
        "items-MAX_NUM_FORMS": "1000",
        "items-0-id": str(first_item.id),
        "items-0-product": str(first_product.id),
        "items-0-warehouse": str(warehouse.id),
        "items-0-quantity": "4",
        "items-1-id": str(second_item.id),
        "items-1-product": str(second_product.id),
        "items-1-warehouse": str(warehouse.id),
        "items-1-quantity": "1",
        "items-1-DELETE": "on",
    }

    response = client.post(f"/orders/{order.id}/edit/", data)

    order.refresh_from_db()
    assert response.status_code == 302
    assert order.customer_name == "Updated Customer"
    assert order.total_amount == Decimal("20.00")
    assert order.items.count() == 1
    assert order.items.get().quantity == 4


def test_non_draft_order_cannot_be_edited(client):
    user = create_user()
    order = create_order(status=Order.Status.RESERVED)
    client.force_login(user)

    assert client.get(f"/orders/{order.id}/edit/").status_code == 403
    assert client.post(f"/orders/{order.id}/edit/", {}).status_code == 403


def test_order_list_search_status_date_filters_and_pagination(client):
    user = create_user()
    old = create_order(
        "ORD-OLD",
        status=Order.Status.CANCELLED,
        customer_email="old@example.com",
    )
    target = create_order(
        "ORD-TARGET",
        status=Order.Status.RESERVED,
        customer_email="target@example.com",
    )
    Order.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=5))
    for index in range(20):
        create_order(f"ORD-PAGE-{index:02d}")
    client.force_login(user)
    today = timezone.localdate().isoformat()

    filtered = client.get(
        "/orders/",
        {
            "q": "target@example.com",
            "status": "reserved",
            "created_after": today,
            "created_before": today,
        },
    )
    second_page = client.get("/orders/", {"page": 2})

    assert list(filtered.context["page_obj"].object_list) == [target]
    assert second_page.context["page_obj"].number == 2
    assert len(second_page.context["page_obj"]) == 2


def test_order_detail_displays_items_totals_and_context_actions(client):
    user = create_user()
    product = create_product(price="6.00")
    warehouse = create_warehouse()
    order = create_order(total_amount=Decimal("12.00"))
    create_item(order, product, warehouse, quantity=2)
    client.force_login(user)

    response = client.get(f"/orders/{order.id}/")
    content = response.content.decode("utf-8")

    assert response.status_code == 200
    assert "12.00" in content
    assert product.sku in content
    assert "Edit draft" in content
    assert ">Reserve<" in content
    assert ">Confirm<" not in content
    assert ">Ship<" not in content


def test_reserve_confirm_and_ship_actions_call_services(client):
    user = create_user()
    product = create_product(price="4.00")
    warehouse = create_warehouse()
    inventory = Inventory.objects.create(product=product, warehouse=warehouse, quantity=10)
    order = create_order()
    create_item(order, product, warehouse, quantity=2)
    client.force_login(user)

    reserve_response = client.post(f"/orders/{order.id}/reserve/")
    order.refresh_from_db()
    inventory.refresh_from_db()
    assert reserve_response.status_code == 302
    assert order.status == Order.Status.RESERVED
    assert inventory.quantity == 10
    assert inventory.reserved_quantity == 2

    confirm_response = client.post(f"/orders/{order.id}/confirm/")
    order.refresh_from_db()
    inventory.refresh_from_db()
    assert confirm_response.status_code == 302
    assert order.status == Order.Status.CONFIRMED
    assert inventory.quantity == 8
    assert inventory.reserved_quantity == 0

    ship_response = client.post(f"/orders/{order.id}/ship/")
    order.refresh_from_db()
    inventory.refresh_from_db()
    assert ship_response.status_code == 302
    assert order.status == Order.Status.SHIPPED
    assert inventory.quantity == 8
    assert StockMovement.objects.count() == 2


def test_cancel_action_releases_reservation_and_records_reason(client):
    user = create_user()
    product = create_product()
    warehouse = create_warehouse()
    inventory = Inventory.objects.create(
        product=product,
        warehouse=warehouse,
        quantity=10,
        reserved_quantity=2,
    )
    order = create_order(status=Order.Status.RESERVED)
    create_item(order, product, warehouse, quantity=2)
    client.force_login(user)

    response = client.post(
        f"/orders/{order.id}/cancel/",
        {"reason": "Customer request"},
    )

    order.refresh_from_db()
    inventory.refresh_from_db()
    assert response.status_code == 302
    assert order.status == Order.Status.CANCELLED
    assert inventory.quantity == 10
    assert inventory.reserved_quantity == 0
    movement = StockMovement.objects.get()
    assert "reason=Customer request" in movement.description


def test_insufficient_stock_conflict_is_displayed_clearly(client):
    user = create_user()
    product = create_product("SHORT")
    warehouse = create_warehouse("LIMITED")
    inventory = Inventory.objects.create(
        product=product,
        warehouse=warehouse,
        quantity=3,
        reserved_quantity=1,
    )
    order = create_order()
    create_item(order, product, warehouse, quantity=4)
    client.force_login(user)

    response = client.post(f"/orders/{order.id}/reserve/", follow=True)
    content = response.content.decode("utf-8")

    assert response.status_code == 200
    assert "One or more order items do not have enough available stock" in content
    assert "SHORT at LIMITED: requested 4, available 2." in content
    order.refresh_from_db()
    inventory.refresh_from_db()
    assert order.status == Order.Status.DRAFT
    assert inventory.reserved_quantity == 1


def test_empty_order_reservation_error_is_displayed(client):
    user = create_user()
    order = create_order()
    client.force_login(user)

    response = client.post(f"/orders/{order.id}/reserve/", follow=True)

    order.refresh_from_db()
    assert response.status_code == 200
    assert (
        "An order must contain at least one item before it can be reserved"
        in response.content.decode("utf-8")
    )
    assert order.status == Order.Status.DRAFT
    assert order.reserved_at is None
    assert StockMovement.objects.count() == 0
    assert AuditLog.objects.count() == 0


def test_warehouse_staff_can_view_orders_but_cannot_write_or_transition(client):
    user = create_user("order-staff", User.Role.WAREHOUSE_STAFF)
    product = create_product()
    warehouse = create_warehouse()
    Inventory.objects.create(product=product, warehouse=warehouse, quantity=10)
    order = create_order()
    create_item(order, product, warehouse)
    client.force_login(user)

    list_response = client.get("/orders/")
    detail_response = client.get(f"/orders/{order.id}/")
    content = detail_response.content.decode("utf-8")

    assert list_response.status_code == 200
    assert detail_response.status_code == 200
    assert client.get("/orders/new/").status_code == 403
    assert client.post(f"/orders/{order.id}/reserve/").status_code == 403
    assert f"/orders/{order.id}/reserve/" not in content
    assert f"/orders/{order.id}/edit/" not in content


def test_order_action_requires_csrf():
    user = create_user("order-csrf")
    order = create_order()
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(user)

    response = csrf_client.post(f"/orders/{order.id}/reserve/")

    assert response.status_code == 403
    order.refresh_from_db()
    assert order.status == Order.Status.DRAFT


def test_order_list_and_detail_have_bounded_query_counts(
    client,
    django_assert_max_num_queries,
):
    user = create_user()
    warehouse = create_warehouse()
    for index in range(15):
        product = create_product(f"QUERY-{index:02d}")
        order = create_order(f"ORD-QUERY-{index:02d}")
        create_item(order, product, warehouse)
    detail_order = Order.objects.first()
    client.force_login(user)

    with django_assert_max_num_queries(6):
        list_response = client.get("/orders/")
    with django_assert_max_num_queries(6):
        detail_response = client.get(f"/orders/{detail_order.id}/")

    assert list_response.status_code == 200
    assert detail_response.status_code == 200
