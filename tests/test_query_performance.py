from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.orders.models import Order, OrderItem
from apps.products.models import Product, Warehouse
from apps.users.models import User


pytestmark = pytest.mark.django_db


@pytest.fixture
def api_client():
    user = User.objects.create_user(
        username="query-manager",
        password="test-password",
        role=User.Role.MANAGER,
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def create_product(sku):
    return Product.objects.create(
        name=f"Product {sku}",
        sku=sku,
        category="Performance",
        unit_price=Decimal("10.00"),
        low_stock_threshold=2,
    )


def create_warehouse():
    return Warehouse.objects.create(
        name="Performance Warehouse",
        code="PERF-WH",
        address="Test address",
    )


def test_order_api_read_queries_do_not_grow_with_orders_or_items(
    api_client,
    django_assert_num_queries,
):
    products = [create_product(f"PERF-{index}") for index in range(2)]
    warehouse = create_warehouse()
    orders = [
        Order.objects.create(
            order_number=f"PERF-ORDER-{index:02d}",
            customer_name="Performance Customer",
            customer_email=f"customer-{index}@example.com",
        )
        for index in range(15)
    ]
    OrderItem.objects.bulk_create(
        [
            OrderItem(
                order=order,
                product=product,
                warehouse=warehouse,
                quantity=1,
                unit_price=product.unit_price,
                subtotal=product.unit_price,
            )
            for order in orders
            for product in products
        ]
    )

    with django_assert_num_queries(3):
        list_response = api_client.get("/api/orders/")

    with django_assert_num_queries(2):
        detail_response = api_client.get(f"/api/orders/{orders[0].id}/")

    assert list_response.status_code == 200
    assert len(list_response.data["results"]) == 15
    assert all(len(order["items"]) == 2 for order in list_response.data["results"])
    assert detail_response.status_code == 200
    assert len(detail_response.data["items"]) == 2


def test_order_create_query_growth_is_bounded_by_bulk_relation_validation(api_client):
    products = [create_product(f"WRITE-{index}") for index in range(10)]
    warehouse = create_warehouse()

    def payload(order_number, selected_products):
        return {
            "order_number": order_number,
            "customer_name": "Performance Customer",
            "customer_email": "performance@example.com",
            "items": [
                {
                    "product": product.id,
                    "warehouse": warehouse.id,
                    "quantity": 1,
                }
                for product in selected_products
            ],
        }

    with CaptureQueriesContext(connection) as single_item_queries:
        single_response = api_client.post(
            "/api/orders/",
            payload("PERF-WRITE-ONE", products[:1]),
            format="json",
        )

    with CaptureQueriesContext(connection) as ten_item_queries:
        ten_response = api_client.post(
            "/api/orders/",
            payload("PERF-WRITE-TEN", products),
            format="json",
        )

    assert single_response.status_code == 201
    assert ten_response.status_code == 201
    assert len(ten_response.data["items"]) == 10
    assert len(ten_item_queries) <= len(single_item_queries) + 2
