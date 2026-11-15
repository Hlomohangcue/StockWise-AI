from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from backend.app import main as main_module
from backend.app.database import Base, create_database_engine, get_db
from backend.app.models import Product


@pytest.fixture
def test_database(tmp_path, monkeypatch):
    database_file = tmp_path / "product-api" / "test.db"
    test_engine = create_database_engine(f"sqlite:///{database_file.as_posix()}")
    monkeypatch.setattr(main_module, "engine", test_engine)
    factory = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)

    def override_get_db():
        with factory() as session:
            yield session

    main_module.app.dependency_overrides[get_db] = override_get_db
    try:
        yield factory
    finally:
        main_module.app.dependency_overrides.clear()
        test_engine.dispose()


@pytest.fixture
def client(test_database):
    with TestClient(main_module.app) as test_client:
        yield test_client


def product_payload(**overrides):
    payload = {
        "sku": "SKU-001",
        "name": "Tea",
        "description": "Black tea",
        "category": "Beverages",
        "unit": "box",
        "cost_price": "1.25",
        "selling_price": "2.50",
        "reorder_level": 5,
        "safety_stock": 2,
        "lead_time_days": 3,
    }
    payload.update(overrides)
    return payload


def create_product(client, **overrides):
    return client.post("/api/v1/products", json=product_payload(**overrides))


def test_create_product_returns_created_product_with_decimal_values(client):
    response = create_product(client)

    assert response.status_code == 201
    assert response.json()["id"] == 1
    assert response.json()["sku"] == "SKU-001"
    assert response.json()["cost_price"] == "1.25"
    assert response.json()["selling_price"] == "2.50"
    assert response.json()["is_active"] is True
    assert response.json()["created_at"]
    assert response.json()["updated_at"]
    assert "stock" not in response.json()


def test_duplicate_sku_returns_conflict(client):
    assert create_product(client).status_code == 201

    response = create_product(client, name="Another product")

    assert response.status_code == 409
    assert response.json()["detail"] == "A product with this SKU already exists."


def test_product_listing_supports_pagination_and_total_information(client):
    for sku in ("SKU-001", "SKU-002", "SKU-003"):
        assert create_product(client, sku=sku).status_code == 201

    response = client.get("/api/v1/products?page=2&page_size=2")
    body = response.json()

    assert response.status_code == 200
    assert len(body["items"]) == 1
    assert body["items"][0]["sku"] == "SKU-003"
    assert body["total"] == 3
    assert body["page"] == 2
    assert body["page_size"] == 2
    assert body["total_pages"] == 2
    assert body["has_next"] is False
    assert body["has_previous"] is True


def test_product_listing_can_filter_active_and_inactive_products(client):
    active = create_product(client).json()
    inactive = create_product(client, sku="SKU-002").json()
    assert client.patch(f"/api/v1/products/{inactive['id']}", json={"is_active": False}).status_code == 200

    active_response = client.get("/api/v1/products?is_active=true")
    inactive_response = client.get("/api/v1/products?is_active=false")

    assert active_response.status_code == inactive_response.status_code == 200
    assert [item["id"] for item in active_response.json()["items"]] == [active["id"]]
    assert [item["id"] for item in inactive_response.json()["items"]] == [inactive["id"]]
    assert active_response.json()["total"] == inactive_response.json()["total"] == 1


def test_retrieve_existing_and_nonexistent_product(client):
    created = create_product(client).json()

    existing_response = client.get(f"/api/v1/products/{created['id']}")
    missing_response = client.get("/api/v1/products/999")

    assert existing_response.status_code == 200
    assert existing_response.json()["id"] == created["id"]
    assert missing_response.status_code == 404


def test_retrieve_inactive_product_after_deactivation(client):
    created = create_product(client).json()

    delete_response = client.delete(f"/api/v1/products/{created['id']}")
    retrieve_response = client.get(f"/api/v1/products/{created['id']}")

    assert delete_response.status_code == 200
    assert retrieve_response.status_code == 200
    assert retrieve_response.json()["id"] == created["id"]
    assert retrieve_response.json()["is_active"] is False


def test_patch_nonexistent_product_returns_not_found(client):
    response = client.patch("/api/v1/products/999", json={"name": "Missing product"})

    assert response.status_code == 404


def test_patch_updates_only_supplied_fields(client):
    created = create_product(client).json()

    response = client.patch(f"/api/v1/products/{created['id']}", json={"name": "Green tea"})

    assert response.status_code == 200
    updated = response.json()
    assert updated["name"] == "Green tea"
    assert updated["sku"] == created["sku"]
    assert updated["unit"] == created["unit"]
    assert updated["cost_price"] == created["cost_price"]
    assert updated["created_at"] == created["created_at"]


@pytest.mark.parametrize(
    "payload",
    [
        product_payload(cost_price="-0.01"),
        product_payload(selling_price="-1"),
        product_payload(reorder_level=-1),
        product_payload(safety_stock=-1),
        product_payload(lead_time_days=-1),
        product_payload(sku="   "),
        {key: value for key, value in product_payload().items() if key != "name"},
        product_payload(id=123),
    ],
)
def test_invalid_product_data_returns_validation_error(client, payload):
    response = client.post("/api/v1/products", json=payload)

    assert response.status_code == 422


@pytest.mark.parametrize(
    "patch",
    [{}, {"name": None}, {"cost_price": -1}, {"id": 5}, {"created_at": "2024-01-01T00:00:00"}],
)
def test_invalid_patch_data_returns_validation_error(client, patch):
    created = create_product(client).json()

    response = client.patch(f"/api/v1/products/{created['id']}", json=patch)

    assert response.status_code == 422


def test_patch_duplicate_sku_returns_conflict(client):
    first = create_product(client).json()
    second = create_product(client, sku="SKU-002").json()

    response = client.patch(f"/api/v1/products/{second['id']}", json={"sku": first["sku"]})

    assert response.status_code == 409


def test_duplicate_sku_rolls_back_session_and_allows_subsequent_create(client, test_database):
    original = create_product(client).json()
    session_factory_override = main_module.app.dependency_overrides[get_db]

    with test_database() as session:
        def use_same_session():
            yield session

        main_module.app.dependency_overrides[get_db] = use_same_session
        try:
            duplicate_response = create_product(client, name="Duplicate SKU")
            subsequent_response = create_product(
                client,
                sku="SKU-002",
                name="Valid subsequent product",
            )

            assert duplicate_response.status_code == 409
            assert subsequent_response.status_code == 201
            assert subsequent_response.json()["sku"] == "SKU-002"

            original_after_failure = session.get(Product, original["id"])
            assert original_after_failure is not None
            assert original_after_failure.sku == original["sku"]
            assert original_after_failure.name == original["name"]
        finally:
            main_module.app.dependency_overrides[get_db] = session_factory_override


def test_delete_deactivates_and_preserves_database_record(client, test_database):
    created = create_product(client).json()

    response = client.delete(f"/api/v1/products/{created['id']}")

    assert response.status_code == 200
    assert response.json()["is_active"] is False
    with test_database() as session:
        stored_product = session.scalar(select(Product).where(Product.id == created["id"]))
        assert stored_product is not None
        assert stored_product.is_active is False


def test_delete_nonexistent_product_returns_not_found(client):
    assert client.delete("/api/v1/products/999").status_code == 404


def test_list_query_parameters_are_validated(client):
    assert client.get("/api/v1/products?page=0").status_code == 422
    assert client.get("/api/v1/products?page_size=101").status_code == 422


def test_product_response_prices_are_decimal_compatible(client):
    response = create_product(client, cost_price=Decimal("12.30").to_eng_string())

    assert response.status_code == 201
    assert response.json()["cost_price"] == "12.30"
