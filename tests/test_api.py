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
    assert movements_response.data[0]["movement_type"] == StockMovement.MovementType.STOCK_IN


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
