from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.inventory.models import Inventory, StockMovement
from apps.orders.models import Order, OrderItem
from apps.products.models import Product, Warehouse
from apps.users.models import User


pytestmark = pytest.mark.django_db


def create_user(username="manager"):
    return User.objects.create_user(
        username=username,
        password="test-password",
        role=User.Role.MANAGER,
    )


@pytest.fixture
def client():
    user = create_user()
    api_client = APIClient()
    api_client.force_authenticate(user=user)
    api_client.user = user
    return api_client


def create_product(sku="SKU-1", price="10.00", is_active=True):
    return Product.objects.create(
        name=f"Product {sku}",
        sku=sku,
        category="General",
        unit_price=Decimal(price),
        low_stock_threshold=1,
        is_active=is_active,
    )


def create_warehouse(code="WH-1", is_active=True):
    return Warehouse.objects.create(
        name=f"Warehouse {code}",
        code=code,
        address="Test address",
        is_active=is_active,
    )


def create_order(status=Order.Status.DRAFT):
    return Order.objects.create(
        order_number="ORD-1",
        customer_name="Customer",
        customer_email="customer@example.com",
        status=status,
    )


def create_order_item(order, product, warehouse, quantity=2):
    return OrderItem.objects.create(
        order=order,
        product=product,
        warehouse=warehouse,
        quantity=quantity,
        unit_price=product.unit_price,
        subtotal=Decimal(quantity) * product.unit_price,
    )


def test_product_crud_and_patch_uses_update_service_audit(client):
    create_response = client.post(
        "/api/products/",
        {
            "name": "Widget",
            "sku": "W-1",
            "category": "Parts",
            "unit_price": "12.00",
            "low_stock_threshold": 3,
            "is_active": True,
        },
        format="json",
    )

    assert create_response.status_code == 201
    product_id = create_response.data["id"]
    list_response = client.get("/api/products/")
    detail_response = client.get(f"/api/products/{product_id}/")
    patch_response = client.patch(
        f"/api/products/{product_id}/",
        {"unit_price": "14.50"},
        format="json",
    )

    assert list_response.status_code == 200
    assert detail_response.status_code == 200
    assert patch_response.status_code == 200
    assert patch_response.data["unit_price"] == "14.50"
    assert AuditLog.objects.get().action == AuditLog.Action.PRODUCT_UPDATED

    delete_response = client.delete(f"/api/products/{product_id}/")
    assert delete_response.status_code == 204


def test_product_and_order_put_are_not_allowed(client):
    product = create_product()
    order = create_order()

    product_response = client.put(
        f"/api/products/{product.id}/",
        {
            "name": "PUT Product",
            "sku": product.sku,
            "category": product.category,
            "unit_price": "99.00",
            "low_stock_threshold": 5,
            "is_active": False,
        },
        format="json",
    )
    order_response = client.put(
        f"/api/orders/{order.id}/",
        {
            "order_number": order.order_number,
            "customer_name": "PUT Customer",
            "customer_email": "put@example.com",
        },
        format="json",
    )
    order_delete_response = client.delete(f"/api/orders/{order.id}/")

    product.refresh_from_db()
    order.refresh_from_db()
    assert product_response.status_code == 405
    assert order_response.status_code == 405
    assert order_delete_response.status_code == 405
    assert order_delete_response.data["error"]["code"] == "METHOD_NOT_ALLOWED"
    assert product.name == "Product SKU-1"
    assert product.unit_price == Decimal("10.00")
    assert order.customer_name == "Customer"
    assert Order.objects.filter(pk=order.pk).exists()
    assert AuditLog.objects.count() == 0


def test_warehouse_endpoints(client):
    create_response = client.post(
        "/api/warehouses/",
        {
            "name": "Main Warehouse",
            "code": "MAIN",
            "address": "Street",
            "is_active": True,
        },
        format="json",
    )

    assert create_response.status_code == 201
    warehouse_id = create_response.data["id"]
    assert client.get("/api/warehouses/").status_code == 200
    assert client.get(f"/api/warehouses/{warehouse_id}/").status_code == 200
    patch_response = client.patch(
        f"/api/warehouses/{warehouse_id}/",
        {"address": "New Street"},
        format="json",
    )
    assert patch_response.status_code == 200
    assert patch_response.data["address"] == "New Street"


def test_inventory_list_detail_adjustment_and_movements(client):
    product = create_product()
    warehouse = create_warehouse()
    inventory = Inventory.objects.create(product=product, warehouse=warehouse, quantity=10)

    assert client.get("/api/inventory/").status_code == 200
    detail_response = client.get(f"/api/inventory/{inventory.id}/")
    assert detail_response.status_code == 200
    assert detail_response.data["available_quantity"] == 10

    adjustment_response = client.post(
        "/api/inventory/adjustments/",
        {
            "product_id": product.id,
            "warehouse_id": warehouse.id,
            "adjustment_type": "stock_in",
            "quantity": 5,
            "description": "received",
        },
        format="json",
    )
    assert adjustment_response.status_code == 200
    assert adjustment_response.data["quantity"] == 15
    assert AuditLog.objects.get().action == AuditLog.Action.INVENTORY_ADJUSTED

    movements_response = client.get(f"/api/inventory/{inventory.id}/movements/")
    assert movements_response.status_code == 200
    assert movements_response.data["count"] == 1
    assert (
        movements_response.data["results"][0]["movement_type"]
        == StockMovement.MovementType.STOCK_IN
    )


def test_inventory_movements_are_paginated_bounded_and_inventory_scoped(
    client,
    django_assert_num_queries,
):
    product = create_product()
    second_product = create_product(sku="SKU-2")
    warehouse = create_warehouse()
    inventory = Inventory.objects.create(
        product=product,
        warehouse=warehouse,
        quantity=200,
    )
    other_inventory = Inventory.objects.create(
        product=second_product,
        warehouse=warehouse,
        quantity=10,
    )
    StockMovement.objects.bulk_create(
        [
            StockMovement(
                inventory=inventory,
                movement_type=StockMovement.MovementType.STOCK_IN,
                quantity=1,
                description=f"Movement {index}",
                created_by=client.user,
            )
            for index in range(105)
        ]
    )
    StockMovement.objects.bulk_create(
        [
            StockMovement(
                inventory=other_inventory,
                movement_type=StockMovement.MovementType.STOCK_IN,
                quantity=1,
                description=f"Other movement {index}",
                created_by=client.user,
            )
            for index in range(3)
        ]
    )

    with django_assert_num_queries(3):
        first_page = client.get(
            f"/api/inventory/{inventory.id}/movements/",
            {"page_size": 500},
        )

    second_page = client.get(
        f"/api/inventory/{inventory.id}/movements/",
        {"page_size": 100, "page": 2},
    )

    assert first_page.status_code == 200
    assert set(first_page.data) == {"count", "next", "previous", "results"}
    assert first_page.data["count"] == 105
    assert len(first_page.data["results"]) == 100
    assert first_page.data["next"] is not None
    assert first_page.data["previous"] is None
    assert {
        movement["inventory"] for movement in first_page.data["results"]
    } == {inventory.id}

    assert second_page.status_code == 200
    assert second_page.data["count"] == 105
    assert len(second_page.data["results"]) == 5
    assert second_page.data["next"] is None
    assert second_page.data["previous"] is not None
    assert {
        movement["inventory"] for movement in second_page.data["results"]
    } == {inventory.id}


def test_order_create_ignores_price_total_status_and_validates_duplicates(client):
    product = create_product(price="9.99")
    warehouse = create_warehouse()

    response = client.post(
        "/api/orders/",
        {
            "order_number": "ORD-API-1",
            "customer_name": "Customer",
            "customer_email": "customer@example.com",
            "status": "shipped",
            "total_amount": "999.99",
            "items": [
                {
                    "product": product.id,
                    "warehouse": warehouse.id,
                    "quantity": 2,
                    "unit_price": "1.00",
                    "subtotal": "2.00",
                }
            ],
        },
        format="json",
    )

    assert response.status_code == 201
    assert response.data["status"] == Order.Status.DRAFT
    assert response.data["total_amount"] == "19.98"
    assert response.data["items"][0]["unit_price"] == "9.99"

    duplicate_response = client.post(
        "/api/orders/",
        {
            "order_number": "ORD-API-2",
            "customer_name": "Customer",
            "customer_email": "customer@example.com",
            "items": [
                {"product": product.id, "warehouse": warehouse.id, "quantity": 1},
                {"product": product.id, "warehouse": warehouse.id, "quantity": 1},
            ],
        },
        format="json",
    )
    assert duplicate_response.status_code == 400


def test_draft_order_patch_replaces_items_but_non_draft_item_edit_is_rejected(client):
    product = create_product(price="5.00")
    second_product = create_product(sku="SKU-2", price="7.00")
    warehouse = create_warehouse()
    order = create_order()
    create_order_item(order, product, warehouse, quantity=1)

    patch_response = client.patch(
        f"/api/orders/{order.id}/",
        {
            "items": [
                {"product": second_product.id, "warehouse": warehouse.id, "quantity": 3}
            ]
        },
        format="json",
    )
    assert patch_response.status_code == 200
    assert patch_response.data["total_amount"] == "21.00"
    assert patch_response.data["items"][0]["product"] == second_product.id

    order.status = Order.Status.RESERVED
    order.save(update_fields=["status", "updated_at"])
    rejected_response = client.patch(
        f"/api/orders/{order.id}/",
        {"items": [{"product": product.id, "warehouse": warehouse.id, "quantity": 1}]},
        format="json",
    )
    assert rejected_response.status_code == 400
    assert rejected_response.data["error"]["code"] == "VALIDATION_ERROR"


def test_order_transition_actions_use_services_and_error_structure(client):
    product = create_product(price="4.00")
    warehouse = create_warehouse()
    inventory = Inventory.objects.create(product=product, warehouse=warehouse, quantity=10)
    order = create_order()
    create_order_item(order, product, warehouse, quantity=2)

    reserve_response = client.post(
        f"/api/orders/{order.id}/reserve/",
        HTTP_IDEMPOTENCY_KEY="reserve-api-1",
    )
    assert reserve_response.status_code == 200
    assert reserve_response.data["status"] == Order.Status.RESERVED
    inventory.refresh_from_db()
    assert inventory.quantity == 10
    assert inventory.reserved_quantity == 2

    repeated_reserve = client.post(
        f"/api/orders/{order.id}/reserve/",
        HTTP_IDEMPOTENCY_KEY="reserve-api-2",
    )
    assert repeated_reserve.status_code == 409
    assert repeated_reserve.data["error"]["code"] == "INVALID_ORDER_TRANSITION"

    confirm_response = client.post(f"/api/orders/{order.id}/confirm/")
    assert confirm_response.status_code == 200
    assert confirm_response.data["status"] == Order.Status.CONFIRMED

    ship_response = client.post(f"/api/orders/{order.id}/ship/")
    assert ship_response.status_code == 200
    assert ship_response.data["status"] == Order.Status.SHIPPED


def test_empty_order_reservation_returns_conflict_without_domain_changes(client):
    order = create_order()

    response = client.post(
        f"/api/orders/{order.id}/reserve/",
        HTTP_IDEMPOTENCY_KEY="empty-order-reservation",
    )

    order.refresh_from_db()
    assert response.status_code == 409
    assert response.data["error"]["code"] == "EMPTY_ORDER"
    assert order.status == Order.Status.DRAFT
    assert order.reserved_at is None
    assert StockMovement.objects.count() == 0
    assert AuditLog.objects.count() == 0


def test_order_cancel_action(client):
    product = create_product()
    warehouse = create_warehouse()
    inventory = Inventory.objects.create(
        product=product,
        warehouse=warehouse,
        quantity=10,
        reserved_quantity=2,
    )
    order = create_order(status=Order.Status.RESERVED)
    create_order_item(order, product, warehouse, quantity=2)

    response = client.post(
        f"/api/orders/{order.id}/cancel/",
        {"reason": "customer request"},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["status"] == Order.Status.CANCELLED
    inventory.refresh_from_db()
    assert inventory.quantity == 10
    assert inventory.reserved_quantity == 0
    audit = AuditLog.objects.get(action=AuditLog.Action.ORDER_CANCELLED)
    assert audit.metadata["source"] == "manual"
