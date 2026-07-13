import csv
import io
from datetime import datetime
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.inventory.models import Inventory
from apps.products.models import Product, Warehouse
from apps.reports.views import CSV_COLUMNS
from apps.users.models import User


pytestmark = pytest.mark.django_db


@pytest.fixture
def client():
    user = User.objects.create_user(
        username="report-manager",
        password="test-password",
        role=User.Role.MANAGER,
    )
    api_client = APIClient()
    api_client.force_authenticate(user=user)
    return api_client


def create_product(sku, name, threshold):
    return Product.objects.create(
        name=name,
        sku=sku,
        category="Parts, Components",
        unit_price=Decimal("10.00"),
        low_stock_threshold=threshold,
    )


def create_warehouse(code, name):
    return Warehouse.objects.create(name=name, code=code)


def response_content(response):
    return b"".join(response.streaming_content).decode("utf-8")


def response_rows(response):
    return list(csv.DictReader(io.StringIO(response_content(response))))


def test_low_stock_csv_headers_filename_content_and_rows(client):
    product = create_product("WIDGET-1", 'Widget, "Large"', threshold=5)
    normal_product = create_product("NORMAL-1", "Normal Widget", threshold=2)
    main = create_warehouse("MAIN", 'Main, "Central" Warehouse')
    overflow = create_warehouse("OVER", "Overflow Warehouse")
    Inventory.objects.create(
        product=product,
        warehouse=main,
        quantity=10,
        reserved_quantity=5,
    )
    Inventory.objects.create(
        product=product,
        warehouse=overflow,
        quantity=2,
        reserved_quantity=2,
    )
    Inventory.objects.create(
        product=normal_product,
        warehouse=main,
        quantity=10,
        reserved_quantity=1,
    )

    response = client.get("/api/reports/low-stock.csv")

    assert response.status_code == 200
    assert response["Content-Type"] == "text/csv"
    assert response["Content-Disposition"].startswith(
        'attachment; filename="stockflow-low-stock-'
    )
    assert response["Content-Disposition"].endswith('.csv"')

    content = response_content(response)
    parsed_rows = list(csv.reader(io.StringIO(content)))
    assert parsed_rows[0] == CSV_COLUMNS
    assert '"Widget, ""Large"""' in content
    assert '"Main, ""Central"" Warehouse"' in content

    rows = list(csv.DictReader(io.StringIO(content)))
    assert len(rows) == 2
    assert {row["warehouse_name"] for row in rows} == {
        'Main, "Central" Warehouse',
        "Overflow Warehouse",
    }
    assert {row["available_quantity"] for row in rows} == {"0", "5"}
    assert {row["sku"] for row in rows} == {"WIDGET-1"}
    assert all(timezone.is_aware(datetime.fromisoformat(row["generated_at"])) for row in rows)


def test_low_stock_csv_uses_one_query_for_multiple_rows(client, django_assert_num_queries):
    warehouse = create_warehouse("QUERY", "Query Warehouse")
    for index in range(12):
        product = create_product(f"LOW-{index:02d}", f"Low Product {index}", threshold=3)
        Inventory.objects.create(
            product=product,
            warehouse=warehouse,
            quantity=5,
            reserved_quantity=3,
        )

    response = client.get("/api/reports/low-stock.csv")
    with django_assert_num_queries(1):
        rows = response_rows(response)

    assert len(rows) == 12


def test_low_stock_csv_rejects_unauthenticated_requests():
    response = APIClient().get("/api/reports/low-stock.csv")

    assert response.status_code == 403


def test_openapi_documents_low_stock_csv(client):
    response = client.get("/api/schema/")

    assert response.status_code == 200
    schema = response.content.decode("utf-8")
    assert "/api/reports/low-stock.csv" in schema
    assert "text/csv" in schema
