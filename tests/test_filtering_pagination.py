from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.inventory.models import Inventory
from apps.inventory.selectors import inventory_with_available_quantity
from apps.orders.models import Order
from apps.products.models import Product, Warehouse
from apps.products.selectors import annotate_product_low_stock
from apps.users.models import User


pytestmark = pytest.mark.django_db


@pytest.fixture
def client():
    user = User.objects.create_user(
        username="filter-manager",
        password="test-password",
        role=User.Role.MANAGER,
    )
    api_client = APIClient()
    api_client.force_authenticate(user=user)
    return api_client


def create_product(
    sku,
    *,
    name=None,
    category="General",
    threshold=2,
    active=True,
    price="10.00",
):
    return Product.objects.create(
        name=name or f"Product {sku}",
        sku=sku,
        category=category,
        unit_price=Decimal(price),
        low_stock_threshold=threshold,
        is_active=active,
    )


def create_warehouse(code):
    return Warehouse.objects.create(name=f"Warehouse {code}", code=code)


def result_ids(response):
    assert response.status_code == 200
    return [item["id"] for item in response.data["results"]]


def test_product_search_and_scalar_filters_run_server_side(client):
    warehouse = create_warehouse("MAIN")
    other_warehouse = create_warehouse("SIDE")
    bolt = create_product("BOLT-1", name="Steel Bolt", category="Parts")
    inactive_tool = create_product(
        "TOOL-1",
        name="Torque Wrench",
        category="Tools",
        active=False,
    )
    other = create_product("OTHER-1", name="Packing Tape", category="Supplies")
    Inventory.objects.create(product=bolt, warehouse=warehouse, quantity=10)
    Inventory.objects.create(product=inactive_tool, warehouse=warehouse, quantity=10)
    Inventory.objects.create(product=other, warehouse=other_warehouse, quantity=10)

    assert result_ids(client.get("/api/products/", {"q": "steel"})) == [bolt.id]
    assert result_ids(client.get("/api/products/", {"q": "tool-1"})) == [inactive_tool.id]
    assert result_ids(client.get("/api/products/", {"q": "SUPPLIES"})) == [other.id]
    assert result_ids(client.get("/api/products/", {"category": "parts"})) == [bolt.id]
    assert result_ids(client.get("/api/products/", {"is_active": "false"})) == [
        inactive_tool.id
    ]
    assert set(result_ids(client.get("/api/products/", {"warehouse": warehouse.id}))) == {
        bolt.id,
        inactive_tool.id,
    }


def test_product_low_stock_uses_exists_without_duplicate_products(client):
    first_warehouse = create_warehouse("WH-A")
    second_warehouse = create_warehouse("WH-B")
    low = create_product("LOW-1", threshold=3)
    healthy = create_product("OK-1", threshold=3)
    no_inventory = create_product("NONE-1", threshold=3)
    Inventory.objects.create(
        product=low,
        warehouse=first_warehouse,
        quantity=5,
        reserved_quantity=3,
    )
    Inventory.objects.create(
        product=low,
        warehouse=second_warehouse,
        quantity=3,
        reserved_quantity=1,
    )
    Inventory.objects.create(product=healthy, warehouse=first_warehouse, quantity=10)

    assert result_ids(client.get("/api/products/", {"low_stock": "true"})) == [low.id]
    assert set(result_ids(client.get("/api/products/", {"low_stock": "false"}))) == {
        healthy.id,
        no_inventory.id,
    }


def test_product_ordering_is_explicit_and_applied(client):
    expensive = create_product("Z-1", name="Zulu", price="30.00")
    cheap = create_product("A-1", name="Alpha", price="5.00")

    assert result_ids(client.get("/api/products/", {"ordering": "-unit_price"})) == [
        expensive.id,
        cheap.id,
    ]


def test_inventory_filters_low_stock_out_of_stock_and_ordering(client):
    main = create_warehouse("MAIN")
    side = create_warehouse("SIDE")
    low_product = create_product("LOW", threshold=3)
    healthy_product = create_product("OK", threshold=3)
    out_product = create_product("OUT", threshold=1)
    low = Inventory.objects.create(
        product=low_product,
        warehouse=main,
        quantity=5,
        reserved_quantity=3,
    )
    healthy = Inventory.objects.create(
        product=healthy_product,
        warehouse=main,
        quantity=10,
        reserved_quantity=1,
    )
    out = Inventory.objects.create(
        product=out_product,
        warehouse=side,
        quantity=4,
        reserved_quantity=4,
    )

    assert result_ids(client.get("/api/inventory/", {"product": low_product.id})) == [low.id]
    assert set(result_ids(client.get("/api/inventory/", {"warehouse": main.id}))) == {
        low.id,
        healthy.id,
    }
    assert set(result_ids(client.get("/api/inventory/", {"low_stock": "true"}))) == {
        low.id,
        out.id,
    }
    assert result_ids(client.get("/api/inventory/", {"low_stock": "false"})) == [
        healthy.id
    ]
    assert result_ids(client.get("/api/inventory/", {"out_of_stock": "true"})) == [out.id]
    assert set(result_ids(client.get("/api/inventory/", {"out_of_stock": "false"}))) == {
        low.id,
        healthy.id,
    }
    assert result_ids(client.get("/api/inventory/", {"ordering": "quantity"})) == [
        out.id,
        low.id,
        healthy.id,
    ]


def test_order_filters_date_range_totals_and_ordering(client):
    now = timezone.now()
    old = Order.objects.create(
        order_number="ORD-OLD",
        customer_name="Old Customer",
        customer_email="old@example.com",
        status=Order.Status.CANCELLED,
        total_amount=Decimal("5.00"),
    )
    middle = Order.objects.create(
        order_number="ORD-MIDDLE",
        customer_name="Middle Customer",
        customer_email="Case@Example.com",
        status=Order.Status.RESERVED,
        total_amount=Decimal("20.00"),
    )
    recent = Order.objects.create(
        order_number="ORD-RECENT",
        customer_name="Recent Customer",
        customer_email="recent@example.com",
        status=Order.Status.RESERVED,
        total_amount=Decimal("50.00"),
    )
    Order.objects.filter(pk=old.pk).update(created_at=now - timedelta(days=3))
    Order.objects.filter(pk=middle.pk).update(created_at=now - timedelta(days=1))
    Order.objects.filter(pk=recent.pk).update(created_at=now)

    assert set(result_ids(client.get("/api/orders/", {"status": "reserved"}))) == {
        middle.id,
        recent.id,
    }
    assert result_ids(
        client.get("/api/orders/", {"customer_email": "case@example.com"})
    ) == [middle.id]
    assert set(
        result_ids(
            client.get(
                "/api/orders/",
                {
                    "created_after": (now - timedelta(days=2)).isoformat(),
                    "created_before": (now + timedelta(minutes=1)).isoformat(),
                },
            )
        )
    ) == {middle.id, recent.id}
    assert result_ids(
        client.get("/api/orders/", {"min_total": "10.00", "max_total": "30.00"})
    ) == [middle.id]
    assert result_ids(client.get("/api/orders/", {"ordering": "total_amount"})) == [
        old.id,
        middle.id,
        recent.id,
    ]


def test_default_pagination_and_page_size_cap(client):
    Product.objects.bulk_create(
        [
            Product(
                name=f"Paged Product {index:03d}",
                sku=f"PAGE-{index:03d}",
                unit_price=Decimal("1.00"),
            )
            for index in range(105)
        ]
    )

    default_response = client.get("/api/products/")
    capped_response = client.get("/api/products/", {"page_size": 500})
    second_page = client.get("/api/products/", {"page_size": 10, "page": 2})

    assert default_response.status_code == 200
    assert default_response.data["count"] == 105
    assert len(default_response.data["results"]) == 20
    assert len(capped_response.data["results"]) == 100
    assert len(second_page.data["results"]) == 10


def test_selector_sql_uses_exists_and_database_arithmetic():
    product_sql = str(
        annotate_product_low_stock(Product.objects.all()).filter(has_low_stock=True).query
    ).upper()
    inventory_sql = str(inventory_with_available_quantity().query).upper()

    assert "EXISTS" in product_sql
    assert "QUANTITY" in product_sql
    assert "RESERVED_QUANTITY" in product_sql
    assert "QUANTITY" in inventory_sql
    assert "RESERVED_QUANTITY" in inventory_sql
    assert "AVAILABLE_QUANTITY_VALUE" in inventory_sql
