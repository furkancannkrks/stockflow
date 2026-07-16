import pytest


pytestmark = pytest.mark.django_db


def get_schema(client):
    response = client.get("/api/schema/")
    assert response.status_code == 200
    return response.data


def test_schema_and_swagger_endpoints_include_metadata_and_authentication(client):
    schema = get_schema(client)
    swagger = client.get("/api/docs/")

    assert swagger.status_code == 200
    assert schema["info"]["title"] == "StockFlow API"
    assert schema["info"]["version"] == "1.0.0"
    assert "HTTP Basic authentication" in schema["info"]["description"]
    assert set(schema["components"]["securitySchemes"]) == {
        "basicAuth",
        "cookieAuth",
    }


def test_custom_actions_document_requests_responses_and_status_codes(client):
    paths = get_schema(client)["paths"]

    create_order = paths["/api/orders/"]["post"]
    assert set(create_order["responses"]) >= {"201", "400", "401", "403", "409"}
    assert (
        create_order["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/OrderWriteRequest"
    )

    reserve = paths["/api/orders/{id}/reserve/"]["post"]
    reserve_parameters = {
        (parameter["name"], parameter["in"]): parameter
        for parameter in reserve["parameters"]
    }
    assert reserve_parameters[("Idempotency-Key", "header")]["required"] is True
    assert set(reserve["responses"]) >= {"200", "400", "401", "403", "404", "409"}
    assert (
        reserve["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/Order"
    )
    assert (
        reserve["responses"]["409"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/APIErrorResponse"
    )

    for action in ("confirm", "ship"):
        operation = paths[f"/api/orders/{{id}}/{action}/"]["post"]
        assert set(operation["responses"]) >= {"200", "401", "403", "404", "409"}

    cancel = paths["/api/orders/{id}/cancel/"]["post"]
    assert set(cancel["responses"]) >= {"200", "400", "401", "403", "404", "409"}

    adjustment = paths["/api/inventory/adjustments/"]["post"]
    assert set(adjustment["responses"]) >= {"200", "400", "401", "403", "404"}
    assert (
        adjustment["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/InventoryAdjustmentRequest"
    )
    assert (
        adjustment["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/Inventory"
    )


def test_required_examples_and_csv_media_type_are_documented(client):
    paths = get_schema(client)["paths"]

    create_order = paths["/api/orders/"]["post"]
    create_request_examples = create_order["requestBody"]["content"]["application/json"][
        "examples"
    ]
    create_response_examples = create_order["responses"]["201"]["content"][
        "application/json"
    ]["examples"]
    assert "CreatingAnOrder" in create_request_examples
    assert "CreatedOrder" in create_response_examples

    reserve = paths["/api/orders/{id}/reserve/"]["post"]
    reserve_request_examples = reserve["requestBody"]["content"]["application/json"][
        "examples"
    ]
    reserve_success_examples = reserve["responses"]["200"]["content"][
        "application/json"
    ]["examples"]
    reserve_conflict_examples = reserve["responses"]["409"]["content"][
        "application/json"
    ]["examples"]
    assert "ReservingAnOrder" in reserve_request_examples
    assert {"ReservedOrder", "SuccessfulIdempotentReplay"} <= set(
        reserve_success_examples
    )
    assert {
        "IdempotencyConflict",
        "InsufficientStock",
        "InvalidTransition",
    } <= set(reserve_conflict_examples)

    adjustment = paths["/api/inventory/adjustments/"]["post"]
    assert "InventoryAdjustment" in adjustment["requestBody"]["content"][
        "application/json"
    ]["examples"]
    assert "AdjustedInventory" in adjustment["responses"]["200"]["content"][
        "application/json"
    ]["examples"]

    csv_response = paths["/api/reports/low-stock.csv"]["get"]["responses"]["200"]
    assert "text/csv" in csv_response["content"]
    assert "CSVExport" in csv_response["content"]["text/csv"]["examples"]
