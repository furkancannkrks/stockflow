from decimal import Decimal

import pytest
from django.test import Client

from apps.audit.models import AuditLog
from apps.inventory.models import Inventory, StockMovement
from apps.products.models import Product, Warehouse
from apps.users.models import User


pytestmark = pytest.mark.django_db


def create_user(username, role=User.Role.MANAGER, **extra_fields):
    return User.objects.create_user(
        username=username,
        password="test-password",
        role=role,
        **extra_fields,
    )


def create_product(sku="VISIBILITY-1"):
    return Product.objects.create(
        name=f"Product {sku}",
        sku=sku,
        category="General",
        unit_price=Decimal("10.00"),
    )


def create_warehouse(code="VISIBILITY-WH"):
    return Warehouse.objects.create(
        name=f"Warehouse {code}",
        code=code,
        address=f"{code} storage address",
    )


def create_inventory_and_movements(actor, count=1):
    inventory = Inventory.objects.create(
        product=create_product(),
        warehouse=create_warehouse(),
        quantity=max(count, 1),
    )
    return StockMovement.objects.bulk_create(
        [
            StockMovement(
                inventory=inventory,
                movement_type=StockMovement.MovementType.STOCK_IN,
                quantity=1,
                reference_type="test",
                reference_id=str(index),
                description=f"Movement {index}",
                created_by=actor,
            )
            for index in range(count)
        ]
    )


def create_audit_logs(actor, count=1):
    return AuditLog.objects.bulk_create(
        [
            AuditLog(
                actor=actor,
                action=AuditLog.Action.INVENTORY_ADJUSTED,
                target_model="inventory.inventory",
                target_object_id=str(index),
                target_repr=f"Inventory {index}",
                metadata={"quantity": {"before": index, "after": index + 1}},
                correlation_id=f"visibility-{index}",
            )
            for index in range(count)
        ]
    )


@pytest.mark.parametrize(
    "path",
    [
        "/audit-logs/",
        "/warehouses/",
        "/warehouses/new/",
        "/stock-movements/",
    ],
)
def test_visibility_pages_redirect_anonymous_users_to_login(client, path):
    response = client.get(path)

    assert response.status_code == 302
    assert response.url == f"/login/?next={path}"


def test_audit_logs_are_manager_and_superuser_only(client):
    manager = create_user("audit-manager")
    staff = create_user("audit-staff", User.Role.WAREHOUSE_STAFF)
    superuser = create_user(
        "audit-superuser",
        User.Role.WAREHOUSE_STAFF,
        is_staff=True,
        is_superuser=True,
    )
    create_audit_logs(manager, 2)

    client.force_login(manager)
    manager_response = client.get("/audit-logs/")
    client.force_login(staff)
    staff_response = client.get("/audit-logs/")
    client.force_login(superuser)
    superuser_response = client.get("/audit-logs/")

    assert manager_response.status_code == 200
    assert b"Inventory adjusted" in manager_response.content
    assert b"audit-manager" in manager_response.content
    assert b"quantity" in manager_response.content
    assert staff_response.status_code == 403
    assert superuser_response.status_code == 200


def test_audit_log_page_is_read_only_and_paginated(client):
    manager = create_user("audit-pagination-manager")
    create_audit_logs(manager, 27)
    client.force_login(manager)

    first_page = client.get("/audit-logs/")
    second_page = client.get("/audit-logs/", {"page": 2})
    post_response = client.post("/audit-logs/", {})

    assert len(first_page.context["page_obj"]) == 25
    assert len(second_page.context["page_obj"]) == 2
    assert post_response.status_code == 405


def test_warehouse_pages_allow_shared_read_but_manager_only_mutation(client):
    manager = create_user("warehouse-manager")
    staff = create_user("warehouse-staff", User.Role.WAREHOUSE_STAFF)
    warehouse = create_warehouse()

    client.force_login(staff)
    staff_list = client.get("/warehouses/")
    staff_detail = client.get(f"/warehouses/{warehouse.id}/")
    staff_create = client.get("/warehouses/new/")
    staff_update = client.get(f"/warehouses/{warehouse.id}/edit/")
    staff_create_post = client.post(
        "/warehouses/new/",
        {"name": "Blocked Warehouse", "code": "BLOCKED-WH", "is_active": True},
    )
    staff_update_post = client.post(
        f"/warehouses/{warehouse.id}/edit/",
        {
            "name": "Blocked Update",
            "code": warehouse.code,
            "address": warehouse.address,
            "is_active": True,
        },
    )

    assert staff_list.status_code == 200
    assert staff_detail.status_code == 200
    assert staff_create.status_code == 403
    assert staff_update.status_code == 403
    assert staff_create_post.status_code == 403
    assert staff_update_post.status_code == 403
    assert Warehouse.objects.filter(code="BLOCKED-WH").exists() is False
    warehouse.refresh_from_db()
    assert warehouse.name == "Warehouse VISIBILITY-WH"

    client.force_login(manager)
    create_response = client.post(
        "/warehouses/new/",
        {
            "name": "Manager Warehouse",
            "code": "MANAGER-WH",
            "address": "Manager address",
            "is_active": True,
        },
    )
    created = Warehouse.objects.get(code="MANAGER-WH")
    update_response = client.post(
        f"/warehouses/{created.id}/edit/",
        {
            "name": "Updated Manager Warehouse",
            "code": "MANAGER-WH",
            "address": "Updated address",
            "is_active": True,
        },
    )

    assert create_response.status_code == 302
    assert create_response.url == f"/warehouses/{created.id}/"
    assert update_response.status_code == 302
    created.refresh_from_db()
    assert created.name == "Updated Manager Warehouse"


def test_warehouse_list_is_paginated(client):
    manager = create_user("warehouse-pagination-manager")
    Warehouse.objects.bulk_create(
        [
            Warehouse(name=f"Warehouse {index:02d}", code=f"PAGE-WH-{index:02d}")
            for index in range(27)
        ]
    )
    client.force_login(manager)

    first_page = client.get("/warehouses/")
    second_page = client.get("/warehouses/", {"page": 2})

    assert len(first_page.context["page_obj"]) == 25
    assert len(second_page.context["page_obj"]) == 2


def test_warehouse_mutation_requires_csrf():
    manager = create_user("warehouse-csrf-manager")
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(manager)

    form_response = csrf_client.get("/warehouses/new/")
    post_response = csrf_client.post(
        "/warehouses/new/",
        {"name": "Blocked", "code": "BLOCKED-CSRF", "is_active": True},
    )

    assert b"csrfmiddlewaretoken" in form_response.content
    assert post_response.status_code == 403
    assert Warehouse.objects.filter(code="BLOCKED-CSRF").exists() is False


def test_stock_movements_are_read_only_for_both_roles_and_paginated(client):
    manager = create_user("movement-manager")
    staff = create_user("movement-staff", User.Role.WAREHOUSE_STAFF)
    movements = create_inventory_and_movements(manager, 27)

    client.force_login(manager)
    manager_first_page = client.get("/stock-movements/")
    manager_second_page = client.get("/stock-movements/", {"page": 2})
    post_response = client.post("/stock-movements/", {})
    client.force_login(staff)
    staff_response = client.get("/stock-movements/")

    assert manager_first_page.status_code == 200
    assert len(manager_first_page.context["page_obj"]) == 25
    assert len(manager_second_page.context["page_obj"]) == 2
    assert movements[-1].description.encode() in manager_first_page.content
    assert post_response.status_code == 405
    assert staff_response.status_code == 200


def test_visibility_page_queries_remain_bounded(
    client,
    django_assert_max_num_queries,
):
    manager = create_user("visibility-query-manager")
    create_audit_logs(manager, 25)
    create_inventory_and_movements(manager, 25)
    Warehouse.objects.bulk_create(
        [
            Warehouse(name=f"Extra Warehouse {index}", code=f"QUERY-WH-{index}")
            for index in range(25)
        ]
    )
    client.force_login(manager)

    with django_assert_max_num_queries(5):
        audit_response = client.get("/audit-logs/")
    with django_assert_max_num_queries(5):
        movement_response = client.get("/stock-movements/")
    with django_assert_max_num_queries(5):
        warehouse_response = client.get("/warehouses/")

    assert audit_response.status_code == 200
    assert movement_response.status_code == 200
    assert warehouse_response.status_code == 200


def test_navigation_shows_only_links_allowed_for_each_role(client):
    manager = create_user("navigation-manager")
    staff = create_user("navigation-staff", User.Role.WAREHOUSE_STAFF)

    client.force_login(manager)
    manager_content = client.get("/").content.decode()
    client.force_login(staff)
    staff_content = client.get("/").content.decode()

    for path in [
        "/warehouses/",
        "/stock-movements/",
        "/audit-logs/",
        "/api/reports/low-stock.csv",
    ]:
        assert path in manager_content

    assert "/warehouses/" in staff_content
    assert "/stock-movements/" in staff_content
    assert "/audit-logs/" not in staff_content
    assert "/api/reports/low-stock.csv" not in staff_content
    assert "Audit Logs" not in staff_content
    assert "Reports" not in staff_content
