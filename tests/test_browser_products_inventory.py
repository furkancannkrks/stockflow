from decimal import Decimal

import pytest
from django.test import Client

from apps.audit.models import AuditLog
from apps.inventory.forms import InventoryAdjustmentForm
from apps.inventory.models import Inventory, StockMovement
from apps.products.forms import ProductForm
from apps.products.models import Product, Warehouse
from apps.users.models import User


pytestmark = pytest.mark.django_db


def create_user(username="browser-manager", role=User.Role.MANAGER):
    return User.objects.create_user(
        username=username,
        password="test-password",
        role=role,
    )


def create_product(
    sku="SKU-1",
    *,
    name=None,
    category="General",
    threshold=2,
    active=True,
):
    return Product.objects.create(
        name=name or f"Product {sku}",
        sku=sku,
        category=category,
        unit_price=Decimal("10.00"),
        low_stock_threshold=threshold,
        is_active=active,
    )


def create_warehouse(code="WH-1"):
    return Warehouse.objects.create(name=f"Warehouse {code}", code=code)


def valid_product_data(**overrides):
    data = {
        "name": "Browser Product",
        "sku": "BROWSER-1",
        "category": "Parts",
        "unit_price": "12.50",
        "low_stock_threshold": 3,
        "is_active": True,
    }
    data.update(overrides)
    return data


def test_product_form_validates_price_and_duplicate_sku():
    create_product("DUPLICATE")

    price_form = ProductForm(data=valid_product_data(unit_price="0"))
    duplicate_form = ProductForm(data=valid_product_data(sku="DUPLICATE"))

    assert price_form.is_valid() is False
    assert "unit_price" in price_form.errors
    assert duplicate_form.is_valid() is False
    assert "sku" in duplicate_form.errors


def test_inventory_adjustment_form_validates_positive_quantity():
    form = InventoryAdjustmentForm(
        data={
            "adjustment_type": "stock_in",
            "quantity": 0,
            "description": "Invalid",
        }
    )

    assert form.is_valid() is False
    assert "quantity" in form.errors


def test_product_list_filters_aggregates_and_low_stock(client):
    user = create_user()
    main = create_warehouse("MAIN")
    side = create_warehouse("SIDE")
    low = create_product("LOW-1", name="Steel Bolt", category="Parts", threshold=3)
    normal = create_product("NORMAL-1", category="Tools", threshold=2)
    inactive = create_product("INACTIVE-1", active=False)
    Inventory.objects.create(
        product=low,
        warehouse=main,
        quantity=10,
        reserved_quantity=8,
    )
    Inventory.objects.create(
        product=low,
        warehouse=side,
        quantity=5,
        reserved_quantity=1,
    )
    Inventory.objects.create(product=normal, warehouse=side, quantity=20)
    client.force_login(user)

    response = client.get(
        "/products/",
        {
            "q": "steel",
            "category": "Parts",
            "is_active": "true",
            "warehouse": main.id,
            "low_stock": "true",
        },
    )

    assert response.status_code == 200
    assert list(response.context["page_obj"].object_list) == [low]
    listed = response.context["page_obj"].object_list[0]
    assert listed.total_inventory == 15
    assert listed.total_reserved_inventory == 9
    assert listed.available_inventory == 6
    assert listed.has_low_stock is True
    assert normal not in response.context["page_obj"].object_list
    assert inactive not in response.context["page_obj"].object_list


def test_product_list_is_paginated(client):
    user = create_user()
    Product.objects.bulk_create(
        [
            Product(
                name=f"Product {index:02d}",
                sku=f"PAGE-{index:02d}",
                unit_price=Decimal("1.00"),
            )
            for index in range(23)
        ]
    )
    client.force_login(user)

    first_page = client.get("/products/")
    second_page = client.get("/products/", {"page": 2})

    assert len(first_page.context["page_obj"]) == 20
    assert len(second_page.context["page_obj"]) == 3


def test_product_detail_shows_warehouse_inventory_and_movements(client):
    user = create_user()
    product = create_product()
    warehouse = create_warehouse()
    inventory = Inventory.objects.create(
        product=product,
        warehouse=warehouse,
        quantity=10,
        reserved_quantity=4,
    )
    movement = StockMovement.objects.create(
        inventory=inventory,
        movement_type=StockMovement.MovementType.STOCK_IN,
        quantity=2,
        description="Delivery",
        created_by=user,
    )
    client.force_login(user)

    response = client.get(f"/products/{product.id}/")

    assert response.status_code == 200
    assert response.context["product"].available_inventory == 6
    assert response.context["inventory_rows"][0].available_quantity_value == 6
    assert response.context["recent_movements"] == [movement]
    assert b"Delivery" in response.content


def test_manager_product_create_and_update_use_redirects_and_audit(client):
    user = create_user()
    client.force_login(user)

    create_response = client.post("/products/new/", valid_product_data())
    product = Product.objects.get(sku="BROWSER-1")
    update_response = client.post(
        f"/products/{product.id}/edit/",
        valid_product_data(name="Updated Browser Product", unit_price="15.00"),
    )

    assert create_response.status_code == 302
    assert create_response.url == f"/products/{product.id}/"
    assert update_response.status_code == 302
    assert update_response.url == f"/products/{product.id}/"
    product.refresh_from_db()
    assert product.name == "Updated Browser Product"
    audit = AuditLog.objects.get(action=AuditLog.Action.PRODUCT_UPDATED)
    assert audit.actor == user
    assert audit.metadata["changes"]["name"]["after"] == "Updated Browser Product"

    detail_response = client.get(update_response.url)
    assert b"was updated" in detail_response.content


def test_warehouse_staff_can_view_but_cannot_manage_products(client):
    user = create_user("browser-staff", User.Role.WAREHOUSE_STAFF)
    product = create_product()
    client.force_login(user)

    assert client.get("/products/").status_code == 200
    assert client.get(f"/products/{product.id}/").status_code == 200
    assert client.get("/products/new/").status_code == 403
    assert client.get(f"/products/{product.id}/edit/").status_code == 403


def test_inventory_list_and_detail_are_available_to_warehouse_staff(client):
    user = create_user("inventory-staff", User.Role.WAREHOUSE_STAFF)
    product = create_product(name="Searchable Gear")
    warehouse = create_warehouse("SEARCH")
    inventory = Inventory.objects.create(
        product=product,
        warehouse=warehouse,
        quantity=8,
        reserved_quantity=3,
    )
    client.force_login(user)

    list_response = client.get(
        "/inventory/",
        {"q": "gear", "warehouse": warehouse.id, "stock_status": "healthy"},
    )
    detail_response = client.get(f"/inventory/{inventory.id}/")

    assert list_response.status_code == 200
    assert list(list_response.context["page_obj"].object_list) == [inventory]
    assert detail_response.status_code == 200
    assert detail_response.context["inventory"].available_quantity_value == 5


def test_stock_adjustment_uses_service_and_redirects_with_message(client):
    user = create_user("adjuster", User.Role.WAREHOUSE_STAFF)
    product = create_product()
    warehouse = create_warehouse()
    inventory = Inventory.objects.create(product=product, warehouse=warehouse, quantity=10)
    client.force_login(user)

    response = client.post(
        f"/inventory/{inventory.id}/adjust/",
        {
            "adjustment_type": "stock_in",
            "quantity": 4,
            "description": "Supplier delivery",
        },
    )

    assert response.status_code == 302
    assert response.url == f"/inventory/{inventory.id}/"
    inventory.refresh_from_db()
    assert inventory.quantity == 14
    movement = StockMovement.objects.get(inventory=inventory)
    assert movement.quantity == 4
    assert movement.created_by == user
    assert AuditLog.objects.get().action == AuditLog.Action.INVENTORY_ADJUSTED

    detail_response = client.get(response.url)
    assert b"adjusted successfully" in detail_response.content


def test_stock_adjustment_domain_error_is_shown_without_changes(client):
    user = create_user("protected-adjuster", User.Role.WAREHOUSE_STAFF)
    product = create_product()
    warehouse = create_warehouse()
    inventory = Inventory.objects.create(
        product=product,
        warehouse=warehouse,
        quantity=10,
        reserved_quantity=4,
    )
    client.force_login(user)

    response = client.post(
        f"/inventory/{inventory.id}/adjust/",
        {
            "adjustment_type": "stock_out",
            "quantity": 7,
            "description": "Blocked removal",
        },
    )

    assert response.status_code == 200
    assert b"Inventory adjustment is not valid" in response.content
    inventory.refresh_from_db()
    assert inventory.quantity == 10
    assert StockMovement.objects.count() == 0
    assert AuditLog.objects.count() == 0


def test_stock_adjustment_requires_csrf():
    user = create_user("csrf-adjuster", User.Role.WAREHOUSE_STAFF)
    product = create_product()
    warehouse = create_warehouse()
    inventory = Inventory.objects.create(product=product, warehouse=warehouse, quantity=10)
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(user)

    response = csrf_client.post(
        f"/inventory/{inventory.id}/adjust/",
        {"adjustment_type": "stock_in", "quantity": 1},
    )

    assert response.status_code == 403
    inventory.refresh_from_db()
    assert inventory.quantity == 10


def test_browser_pages_have_bounded_query_counts(
    client,
    django_assert_max_num_queries,
):
    user = create_user()
    warehouse = create_warehouse("QUERY")
    product = create_product("QUERY-MAIN")
    inventory = Inventory.objects.create(product=product, warehouse=warehouse, quantity=10)
    for index in range(15):
        extra_product = create_product(f"QUERY-{index:02d}")
        extra_inventory = Inventory.objects.create(
            product=extra_product,
            warehouse=warehouse,
            quantity=10,
        )
        StockMovement.objects.create(
            inventory=extra_inventory,
            movement_type=StockMovement.MovementType.STOCK_IN,
            quantity=1,
            created_by=user,
        )
    client.force_login(user)

    with django_assert_max_num_queries(8):
        product_list_response = client.get("/products/")
    with django_assert_max_num_queries(7):
        product_detail_response = client.get(f"/products/{product.id}/")
    with django_assert_max_num_queries(7):
        inventory_list_response = client.get("/inventory/")
    with django_assert_max_num_queries(6):
        inventory_detail_response = client.get(f"/inventory/{inventory.id}/")

    assert product_list_response.status_code == 200
    assert product_detail_response.status_code == 200
    assert inventory_list_response.status_code == 200
    assert inventory_detail_response.status_code == 200
