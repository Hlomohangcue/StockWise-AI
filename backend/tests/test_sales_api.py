from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from backend.app import main as main_module
from backend.app.database import Base, create_database_engine, get_db
from backend.app.models import InventoryBalance, Sale, SaleItem, StockMovement


@pytest.fixture
def sales_context(tmp_path, monkeypatch):
    database_file = tmp_path / "sales-api" / "test.db"
    engine = create_database_engine(f"sqlite:///{database_file.as_posix()}")
    monkeypatch.setattr(main_module, "engine", engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        with factory() as session:
            yield session

    main_module.app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(main_module.app) as client:
            yield client, factory
    finally:
        main_module.app.dependency_overrides.clear()
        engine.dispose()


def product_payload(sku="SALE-API-001", **overrides):
    payload = {
        "sku": sku,
        "name": f"Product {sku}",
        "unit": "item",
        "cost_price": "1.00",
        "selling_price": "2.00",
        "reorder_level": 0,
        "safety_stock": 0,
        "lead_time_days": 0,
    }
    payload.update(overrides)
    return payload


def create_product(client, sku="SALE-API-001", **overrides):
    response = client.post("/api/v1/products", json=product_payload(sku, **overrides))
    assert response.status_code == 201
    return response.json()


def receive(client, product_id, quantity):
    response = client.post(
        "/api/v1/inventory/receive",
        json={"product_id": product_id, "quantity": quantity},
    )
    assert response.status_code == 201


def post_sale(client, items, **overrides):
    return client.post("/api/v1/sales", json={"items": items, **overrides})


def test_create_multiline_sale_records_actual_prices_and_linked_issue_movements(sales_context):
    client, factory = sales_context
    first = create_product(client)
    second = create_product(client, "SALE-API-002")
    receive(client, first["id"], "3.000")
    receive(client, second["id"], "2.000")

    response = post_sale(
        client,
        [
            {"product_id": first["id"], "quantity": "1.125", "unit_price": "2.00"},
            {"product_id": second["id"], "quantity": "0.500", "unit_price": "3.01"},
        ],
        reference="receipt-42",
        sold_at="2025-05-01T12:00:00+02:00",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["reference"] == "receipt-42"
    assert datetime.fromisoformat(body["sold_at"].replace("Z", "+00:00")) == datetime(
        2025, 5, 1, 10, 0, tzinfo=timezone.utc
    )
    assert body["total_amount"] == "3.76"
    assert [item["unit_price"] for item in body["items"]] == ["2.00", "3.01"]
    assert [item["line_total"] for item in body["items"]] == ["2.25", "1.51"]
    assert [item["product_name"] for item in body["items"]] == [first["name"], second["name"]]

    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Sale)) == 1
        assert session.scalar(select(func.count()).select_from(SaleItem)) == 2
        movements = session.scalars(
            select(StockMovement).where(StockMovement.movement_type == "ISSUE").order_by(StockMovement.id)
        ).all()
        items = session.scalars(select(SaleItem).order_by(SaleItem.id)).all()
        assert len(movements) == len(items) == 2
        assert [item.stock_movement_id for item in items] == [movement.id for movement in movements]
        assert [(movement.quantity_before, movement.quantity_after) for movement in movements] == [
            (Decimal("3.000"), Decimal("1.875")),
            (Decimal("2.000"), Decimal("1.500")),
        ]


@pytest.mark.parametrize(
    "line",
    [
        {"product_id": 1, "quantity": "0", "unit_price": "1.00"},
        {"product_id": 1, "quantity": "-1", "unit_price": "1.00"},
        {"product_id": 1, "quantity": "1.0001", "unit_price": "1.00"},
        {"product_id": 1, "quantity": "100000000000", "unit_price": "1.00"},
        {"product_id": 1, "quantity": "1.000", "unit_price": "-0.01"},
        {"product_id": 1, "quantity": "1.000", "unit_price": "1.001"},
    ],
)
def test_invalid_sale_line_returns_422(sales_context, line):
    client, _ = sales_context
    response = post_sale(client, [line])
    assert response.status_code == 422


def test_sale_requires_at_least_one_line_and_timezone_aware_sold_at(sales_context):
    client, _ = sales_context

    assert post_sale(client, []).status_code == 422
    assert post_sale(
        client,
        [{"product_id": 1, "quantity": "1.000", "unit_price": "1.00"}],
        sold_at="2025-05-01T12:00:00",
    ).status_code == 422


def test_unknown_product_returns_404_and_inactive_product_can_be_sold(sales_context):
    client, _ = sales_context
    unknown = post_sale(
        client,
        [{"product_id": 999, "quantity": "1.000", "unit_price": "2.00"}],
    )
    assert unknown.status_code == 404

    product = create_product(client)
    receive(client, product["id"], "1.000")
    assert client.patch(f"/api/v1/products/{product['id']}", json={"is_active": False}).status_code == 200
    sale = post_sale(
        client,
        [{"product_id": product["id"], "quantity": "1.000", "unit_price": "1.75"}],
    )
    assert sale.status_code == 201
    assert sale.json()["items"][0]["unit_price"] == "1.75"


def test_insufficient_stock_returns_conflict_without_creating_sale(sales_context):
    client, factory = sales_context
    product = create_product(client)
    receive(client, product["id"], "1.000")

    response = post_sale(
        client,
        [{"product_id": product["id"], "quantity": "1.001", "unit_price": "2.00"}],
    )

    assert response.status_code == 409
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Sale)) == 0
        assert session.scalar(select(func.count()).select_from(SaleItem)) == 0
        assert session.scalar(select(func.count()).select_from(StockMovement)) == 1
        assert session.scalar(
            select(InventoryBalance.quantity_on_hand).where(InventoryBalance.product_id == product["id"])
        ) == Decimal("1.000")


def test_later_line_failure_rolls_back_header_items_and_earlier_issue(sales_context):
    client, factory = sales_context
    first = create_product(client)
    second = create_product(client, "SALE-API-002")
    receive(client, first["id"], "5.000")
    receive(client, second["id"], "1.000")

    response = post_sale(
        client,
        [
            {"product_id": first["id"], "quantity": "2.000", "unit_price": "2.00"},
            {"product_id": second["id"], "quantity": "2.000", "unit_price": "3.00"},
        ],
    )

    assert response.status_code == 409
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Sale)) == 0
        assert session.scalar(select(func.count()).select_from(SaleItem)) == 0
        assert session.scalar(select(func.count()).select_from(StockMovement)) == 2
        balances = session.scalars(select(InventoryBalance).order_by(InventoryBalance.product_id)).all()
        assert [balance.quantity_on_hand for balance in balances] == [
            Decimal("5.000"), Decimal("1.000")
        ]


def test_sales_history_detail_pagination_product_and_date_filters(sales_context):
    client, _ = sales_context
    first = create_product(client)
    second = create_product(client, "SALE-API-002")
    receive(client, first["id"], "5.000")
    receive(client, second["id"], "5.000")
    created = []
    for product_id, sold_at in (
        (first["id"], "2025-01-01T10:00:00+00:00"),
        (second["id"], "2025-01-02T10:00:00+00:00"),
        (first["id"], "2025-01-03T10:00:00+00:00"),
    ):
        result = post_sale(
            client,
            [{"product_id": product_id, "quantity": "1.000", "unit_price": "2.00"}],
            sold_at=sold_at,
        )
        assert result.status_code == 201
        created.append(result.json())

    product_history = client.get(f"/api/v1/sales?product_id={first['id']}&page_size=1")
    date_history = client.get(
        "/api/v1/sales?sold_from=2025-01-02T00:00:00Z&sold_before=2025-01-04T00:00:00Z"
    )
    detail = client.get(f"/api/v1/sales/{created[0]['id']}")
    paginated = client.get("/api/v1/sales?page=1&page_size=2")

    assert product_history.status_code == date_history.status_code == detail.status_code == paginated.status_code == 200
    assert product_history.json()["total"] == 2
    assert product_history.json()["items"][0]["id"] == created[2]["id"]
    assert date_history.json()["total"] == 2
    assert [item["id"] for item in date_history.json()["items"]] == [
        created[2]["id"], created[1]["id"]
    ]
    assert detail.json()["id"] == created[0]["id"]
    assert len(detail.json()["items"]) == 1
    assert len(paginated.json()["items"]) == 2
    assert paginated.json()["has_next"] is True


def test_sales_history_rejects_invalid_ranges_and_unknown_filters(sales_context):
    client, _ = sales_context
    assert client.get(
        "/api/v1/sales?sold_from=2025-01-02T00:00:00Z&sold_before=2025-01-02T00:00:00Z"
    ).status_code == 422
    assert client.get("/api/v1/sales?sold_from=2025-01-02T00:00:00").status_code == 422
    assert client.get("/api/v1/sales?product_id=999").status_code == 404
    assert client.get("/api/v1/sales/999").status_code == 404


def test_sales_are_append_only_and_openapi_routes_are_registered(sales_context):
    client, _ = sales_context
    product = create_product(client)
    receive(client, product["id"], "1.000")
    sale = post_sale(
        client,
        [{"product_id": product["id"], "quantity": "1.000", "unit_price": "2.00"}],
    ).json()

    assert client.patch(f"/api/v1/sales/{sale['id']}", json={"reference": "changed"}).status_code == 405
    assert client.delete(f"/api/v1/sales/{sale['id']}").status_code == 405
    openapi = client.get("/openapi.json").json()
    assert "/api/v1/sales" in openapi["paths"]
    assert "/api/v1/sales/{sale_id}" in openapi["paths"]
