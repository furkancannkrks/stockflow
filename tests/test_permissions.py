from decimal import Decimal

import pytest
from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory
from rest_framework.test import APIClient

from apps.audit.admin import AuditLogAdmin
from apps.audit.models import AuditLog
from apps.inventory.models import Inventory
from apps.orders.models import Order
from apps.products.models import Product, Warehouse
from apps.users.models import User


pytestmark = pytest.mark.django_db


def create_user(username, role, **extra_fields):
    return User.objects.create_user(
        username=username,
        password="test-password",
        role=role,
        **extra_fields,
    )


def authenticated_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def create_product(sku="SKU-1"):
    return Product.objects.create(
        name=f"Product {sku}",
        sku=sku,
        category="General",
        unit_price=Decimal("10.00"),
        low_stock_threshold=2,
    )


def create_warehouse(code="WH-1"):
    return Warehouse.objects.create(name=f"Warehouse {code}", code=code)


def create_order(order_number, status=Order.Status.DRAFT):
    return Order.objects.create(
        order_number=order_number,
        customer_name="Customer",
        customer_email="customer@example.com",
        status=status,
    )


@pytest.fixture
def manager():
    return create_user("manager-user", User.Role.MANAGER)


@pytest.fixture
def warehouse_staff():
    return create_user("warehouse-user", User.Role.WAREHOUSE_STAFF)


def test_unauthenticated_api_request_returns_401():
    response = APIClient().get("/api/products/")

    assert response.status_code == 401
    assert response["WWW-Authenticate"].startswith("Basic")


def test_warehouse_staff_can_view_core_resources(warehouse_staff):
    product = create_product()
    warehouse = create_warehouse()
    Inventory.objects.create(product=product, warehouse=warehouse, quantity=10)
    create_order("ORD-VIEW")
    client = authenticated_client(warehouse_staff)

    assert client.get("/api/products/").status_code == 200
    assert client.get("/api/warehouses/").status_code == 200
    assert client.get("/api/inventory/").status_code == 200
    assert client.get("/api/orders/").status_code == 200


def test_warehouse_staff_can_adjust_inventory(warehouse_staff):
    product = create_product()
    warehouse = create_warehouse()
    inventory = Inventory.objects.create(product=product, warehouse=warehouse, quantity=10)
    client = authenticated_client(warehouse_staff)

    response = client.post(
        "/api/inventory/adjustments/",
        {
            "product_id": product.id,
            "warehouse_id": warehouse.id,
            "adjustment_type": "stock_in",
            "quantity": 3,
            "description": "Delivery",
        },
        format="json",
    )

    assert response.status_code == 200
    inventory.refresh_from_db()
    assert inventory.quantity == 13


def test_warehouse_staff_cannot_mutate_products_or_warehouses(warehouse_staff):
    product = create_product()
    warehouse = create_warehouse()
    client = authenticated_client(warehouse_staff)

    product_create = client.post(
        "/api/products/",
        {
            "name": "Blocked Product",
            "sku": "BLOCKED",
            "unit_price": "5.00",
        },
        format="json",
    )
    product_update = client.patch(
        f"/api/products/{product.id}/",
        {"name": "Blocked Update"},
        format="json",
    )
    product_delete = client.delete(f"/api/products/{product.id}/")
    warehouse_create = client.post(
        "/api/warehouses/",
        {"name": "Blocked Warehouse", "code": "BLOCKED"},
        format="json",
    )
    warehouse_update = client.patch(
        f"/api/warehouses/{warehouse.id}/",
        {"name": "Blocked Update"},
        format="json",
    )

    assert product_create.status_code == 403
    assert product_update.status_code == 403
    assert product_delete.status_code == 403
    assert warehouse_create.status_code == 403
    assert warehouse_update.status_code == 403
    product.refresh_from_db()
    warehouse.refresh_from_db()
    assert product.name == "Product SKU-1"
    assert warehouse.name == "Warehouse WH-1"


def test_warehouse_staff_cannot_mutate_or_transition_orders(warehouse_staff):
    draft = create_order("ORD-DRAFT")
    reserved_for_confirm = create_order("ORD-CONFIRM", Order.Status.RESERVED)
    reserved_for_cancel = create_order("ORD-CANCEL", Order.Status.RESERVED)
    confirmed = create_order("ORD-SHIP", Order.Status.CONFIRMED)
    client = authenticated_client(warehouse_staff)

    create_response = client.post(
        "/api/orders/",
        {
            "order_number": "ORD-BLOCKED",
            "customer_name": "Blocked",
            "customer_email": "blocked@example.com",
        },
        format="json",
    )
    update_response = client.patch(
        f"/api/orders/{draft.id}/",
        {"customer_name": "Blocked Update"},
        format="json",
    )
    reserve_response = client.post(
        f"/api/orders/{draft.id}/reserve/",
        HTTP_IDEMPOTENCY_KEY="staff-blocked-reserve",
    )
    confirm_response = client.post(f"/api/orders/{reserved_for_confirm.id}/confirm/")
    cancel_response = client.post(f"/api/orders/{reserved_for_cancel.id}/cancel/")
    ship_response = client.post(f"/api/orders/{confirmed.id}/ship/")

    assert create_response.status_code == 403
    assert update_response.status_code == 403
    assert reserve_response.status_code == 403
    assert confirm_response.status_code == 403
    assert cancel_response.status_code == 403
    assert ship_response.status_code == 403


def test_report_export_is_manager_only(manager, warehouse_staff):
    manager_response = authenticated_client(manager).get("/api/reports/low-stock.csv")
    staff_response = authenticated_client(warehouse_staff).get(
        "/api/reports/low-stock.csv"
    )

    assert manager_response.status_code == 200
    assert staff_response.status_code == 403


def test_manager_can_create_products_and_warehouses(manager):
    client = authenticated_client(manager)

    product_response = client.post(
        "/api/products/",
        {
            "name": "Manager Product",
            "sku": "MANAGER-SKU",
            "category": "General",
            "unit_price": "5.00",
            "low_stock_threshold": 1,
            "is_active": True,
        },
        format="json",
    )
    warehouse_response = client.post(
        "/api/warehouses/",
        {"name": "Manager Warehouse", "code": "MANAGER-WH"},
        format="json",
    )

    assert product_response.status_code == 201
    assert warehouse_response.status_code == 201


def test_audit_admin_visibility_is_manager_only(manager, warehouse_staff):
    manager.is_staff = True
    manager.save(update_fields=["is_staff"])
    warehouse_staff.is_staff = True
    warehouse_staff.save(update_fields=["is_staff"])
    superuser = create_user(
        "superuser",
        User.Role.WAREHOUSE_STAFF,
        is_staff=True,
        is_superuser=True,
    )
    admin = AuditLogAdmin(AuditLog, AdminSite())
    request_factory = RequestFactory()

    manager_request = request_factory.get("/admin/audit/auditlog/")
    manager_request.user = manager
    staff_request = request_factory.get("/admin/audit/auditlog/")
    staff_request.user = warehouse_staff
    superuser_request = request_factory.get("/admin/audit/auditlog/")
    superuser_request.user = superuser

    assert admin.has_module_permission(manager_request) is True
    assert admin.has_view_permission(manager_request) is True
    assert admin.has_module_permission(staff_request) is False
    assert admin.has_view_permission(staff_request) is False
    assert admin.has_view_permission(superuser_request) is True


def test_browser_login_and_logout(client):
    user = create_user("browser-manager", User.Role.MANAGER)

    login_page = client.get("/login/")
    login_response = client.post(
        "/login/",
        {"username": user.username, "password": "test-password"},
    )

    assert login_page.status_code == 200
    assert b"csrfmiddlewaretoken" in login_page.content
    assert login_response.status_code == 302
    assert login_response.url == "/"
    assert client.session["_auth_user_id"] == str(user.id)

    logout_response = client.post("/logout/")

    assert logout_response.status_code == 302
    assert logout_response.url == "/login/"
    assert "_auth_user_id" not in client.session
