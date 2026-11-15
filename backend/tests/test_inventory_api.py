from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.app import main as main_module
from backend.app.database import create_database_engine, get_db


@pytest.fixture
def inventory_client(tmp_path, monkeypatch):
    database_file = tmp_path / "inventory-api" / "test.db"
    engine = create_database_engine(f"sqlite:///{database_file.as_posix()}")
    monkeypatch.setattr(main_module, "engine", engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        with factory() as session:
            yield session

    main_module.app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(main_module.app) as client:
            yield client
    finally:
        main_module.app.dependency_overrides.clear()
        engine.dispose()


def product_payload(**overrides):
    payload = {
        "sku": "INVENTORY-001",
        "name": "Inventory test product",
        "unit": "kg",
        "cost_price": "1.00",
        "selling_price": "2.00",
        "reorder_level": 0,
        "safety_stock": 0,
        "lead_time_days": 0,
    }
    payload.update(overrides)
    return payload


def create_product(client, **overrides):
    return client.post("/api/v1/products", json=product_payload(**overrides)).json()


def test_receive_and_balance_for_new_product(inventory_client):
    product = create_product(inventory_client)

    response = inventory_client.post(
        "/api/v1/inventory/receive",
        json={"product_id": product["id"], "quantity": "2.375", "reference": "delivery-1"},
    )

    assert response.status_code == 201
    assert response.json()["balance"]["quantity_on_hand"] == "2.375"
    assert response.json()["movement"]["movement_type"] == "RECEIVE"
    assert response.json()["movement"]["quantity_before"] == "0.000"
    assert response.json()["movement"]["quantity_after"] == "2.375"
    assert response.json()["movement"]["reference"] == "delivery-1"

    balance = inventory_client.get(f"/api/v1/inventory/{product['id']}/balance")
    assert balance.status_code == 200
    assert balance.json()["quantity_on_hand"] == "2.375"


def test_balance_without_movement_is_zero_and_does_not_require_active_product(inventory_client):
    product = create_product(inventory_client, is_active=False)

    response = inventory_client.get(f"/api/v1/inventory/{product['id']}/balance")

    assert response.status_code == 200
    assert response.json()["quantity_on_hand"] == "0.000"
    assert response.json()["sku"] == product["sku"]


def test_receive_existing_inactive_product_is_allowed_and_documented_behavior(inventory_client):
    product = create_product(inventory_client, is_active=False)

    response = inventory_client.post(
        "/api/v1/inventory/receive",
        json={"product_id": product["id"], "quantity": "1.000"},
    )

    assert response.status_code == 201
    assert response.json()["balance"]["quantity_on_hand"] == "1.000"


def test_issue_updates_balance_and_rejects_insufficient_stock(inventory_client):
    product = create_product(inventory_client)
    inventory_client.post(
        "/api/v1/inventory/receive",
        json={"product_id": product["id"], "quantity": "1.250"},
    )

    issued = inventory_client.post(
        "/api/v1/inventory/issue",
        json={"product_id": product["id"], "quantity": "1.250"},
    )
    rejected = inventory_client.post(
        "/api/v1/inventory/issue",
        json={"product_id": product["id"], "quantity": "0.001"},
    )

    assert issued.status_code == 201
    assert issued.json()["balance"]["quantity_on_hand"] == "0.000"
    assert rejected.status_code == 409
    assert "internal" not in rejected.json()["detail"].lower()


@pytest.mark.parametrize("quantity", ["0", "-1", "0.0001", "100000000000"])
def test_movement_rejects_invalid_or_overprecision_quantity(inventory_client, quantity):
    product = create_product(inventory_client)

    response = inventory_client.post(
        "/api/v1/inventory/receive",
        json={"product_id": product["id"], "quantity": quantity},
    )

    assert response.status_code == 422


def test_movement_and_balance_endpoints_return_not_found_for_missing_product(inventory_client):
    receive = inventory_client.post(
        "/api/v1/inventory/receive",
        json={"product_id": 999, "quantity": "1.000"},
    )

    assert receive.status_code == 404
    assert inventory_client.get("/api/v1/inventory/999/balance").status_code == 404
    assert inventory_client.get("/api/v1/inventory/999/movements").status_code == 404


def test_adjustment_increase_decrease_reason_and_no_op(inventory_client):
    product = create_product(inventory_client)
    url = "/api/v1/inventory/adjustments"

    increased = inventory_client.post(
        url,
        json={"product_id": product["id"], "target_quantity": "3.250", "reason": "Opening count"},
    )
    decreased = inventory_client.post(
        url,
        json={"product_id": product["id"], "target_quantity": "2.000", "reason": "Count correction"},
    )
    unchanged = inventory_client.post(
        url,
        json={"product_id": product["id"], "target_quantity": "2.000", "reason": "Count confirmed"},
    )

    assert increased.status_code == decreased.status_code == 201
    assert increased.json()["movement"]["quantity"] == "3.250"
    assert decreased.json()["movement"]["quantity"] == "1.250"
    assert decreased.json()["movement"]["quantity_before"] == "3.250"
    assert decreased.json()["movement"]["quantity_after"] == "2.000"
    assert unchanged.status_code == 200
    assert unchanged.json()["movement"] is None
    assert unchanged.json()["balance"]["quantity_on_hand"] == "2.000"


def test_adjustment_requires_reason_and_nonnegative_target(inventory_client):
    product = create_product(inventory_client)

    missing_reason = inventory_client.post(
        "/api/v1/inventory/adjustments",
        json={"product_id": product["id"], "target_quantity": "1.000"},
    )
    blank_reason = inventory_client.post(
        "/api/v1/inventory/adjustments",
        json={"product_id": product["id"], "target_quantity": "1.000", "reason": "   "},
    )
    negative = inventory_client.post(
        "/api/v1/inventory/adjustments",
        json={"product_id": product["id"], "target_quantity": "-0.001", "reason": "Count"},
    )

    assert missing_reason.status_code == blank_reason.status_code == negative.status_code == 422


def test_movement_history_is_newest_first_filterable_and_paginated(inventory_client):
    first_product = create_product(inventory_client)
    second_product = create_product(inventory_client, sku="INVENTORY-002")
    for product, quantity in ((first_product, "1.000"), (second_product, "2.000"), (first_product, "3.000")):
        inventory_client.post(
            "/api/v1/inventory/receive",
            json={"product_id": product["id"], "quantity": quantity},
        )

    product_history = inventory_client.get(
        f"/api/v1/inventory/{first_product['id']}/movements?page=1&page_size=1"
    )
    global_history = inventory_client.get("/api/v1/inventory/movements?page=1&page_size=2")
    filtered_history = inventory_client.get(
        f"/api/v1/inventory/movements?product_id={second_product['id']}"
    )

    assert product_history.status_code == global_history.status_code == filtered_history.status_code == 200
    assert product_history.json()["total"] == 2
    assert product_history.json()["items"][0]["quantity"] == "3.000"
    assert product_history.json()["has_next"] is True
    assert len(global_history.json()["items"]) == 2
    assert global_history.json()["items"][0]["id"] > global_history.json()["items"][1]["id"]
    assert filtered_history.json()["total"] == 1
    assert filtered_history.json()["items"][0]["product_id"] == second_product["id"]


def test_movement_history_has_no_edit_or_delete_api_routes(inventory_client):
    product = create_product(inventory_client)
    receive = inventory_client.post(
        "/api/v1/inventory/receive",
        json={"product_id": product["id"], "quantity": Decimal("1.000").to_eng_string()},
    )
    movement_id = receive.json()["movement"]["id"]

    assert inventory_client.patch(f"/api/v1/inventory/movements/{movement_id}", json={"reason": "changed"}).status_code == 404
    assert inventory_client.delete(f"/api/v1/inventory/movements/{movement_id}").status_code == 404
