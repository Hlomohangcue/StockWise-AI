from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Event, local

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base, create_database_engine
from backend.app.models import InventoryBalance, Product, Sale, SaleItem, StockMovement
from backend.app.schemas.sales import SaleCreate
from backend.app.services.inventory import InsufficientStockError, receive_stock
from backend.app.services.sales import record_sale


@pytest.fixture
def database(tmp_path):
    database_file = tmp_path / "sales-service" / "test.db"
    engine = create_database_engine(f"sqlite:///{database_file.as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    try:
        yield engine, factory
    finally:
        engine.dispose()


def make_product(session, sku="SALES-001", *, active=True):
    product = Product(
        sku=sku,
        name=f"Product {sku}",
        unit="item",
        cost_price=Decimal("1.00"),
        selling_price=Decimal("2.00"),
        reorder_level=0,
        safety_stock=0,
        lead_time_days=0,
        is_active=active,
    )
    session.add(product)
    session.flush()
    product_id = product.id
    session.commit()
    return product_id


def test_record_multiline_sale_calculates_decimal_totals_and_utc_time(database):
    _, factory = database
    with factory() as session:
        first_product = make_product(session)
        second_product = make_product(session, "SALES-002")
        receive_stock(session, product_id=first_product, quantity=Decimal("3.000"))
        receive_stock(session, product_id=second_product, quantity=Decimal("2.000"))

        sale = record_sale(
            session,
            SaleCreate(
                reference="receipt-17",
                sold_at=datetime(2025, 5, 1, 12, 0, tzinfo=timezone(timedelta(hours=2))),
                items=[
                    {"product_id": first_product, "quantity": "1.125", "unit_price": "2.00"},
                    {"product_id": second_product, "quantity": "0.500", "unit_price": "3.01"},
                ],
            ),
        )

        assert sale.reference == "receipt-17"
        assert sale.sold_at == datetime(2025, 5, 1, 10, 0)
        assert [item.line_total for item in sale.items] == [Decimal("2.25"), Decimal("1.51")]
        assert sale.total_amount == Decimal("3.76")
        assert [item.stock_movement_id for item in sale.items] == [
            movement.id for movement in session.scalars(
                select(StockMovement).where(StockMovement.movement_type == "ISSUE").order_by(StockMovement.id)
            ).all()
        ]
        assert [item.product_name for item in sale.items] == ["Product SALES-001", "Product SALES-002"]


def test_record_sale_defaults_timestamp_and_uses_half_up_line_rounding(database):
    _, factory = database
    with factory() as session:
        product = make_product(session)
        receive_stock(session, product_id=product, quantity=Decimal("2.000"))
        before = datetime.now(timezone.utc).replace(tzinfo=None)

        sale = record_sale(
            session,
            SaleCreate(items=[{"product_id": product, "quantity": "1.005", "unit_price": "1.01"}]),
        )
        after = datetime.now(timezone.utc).replace(tzinfo=None)

        assert before <= sale.sold_at <= after
        assert sale.items[0].line_total == Decimal("1.02")
        assert sale.total_amount == Decimal("1.02")


def test_insufficient_later_line_rolls_back_all_sale_and_inventory_writes(database):
    _, factory = database
    with factory() as session:
        first_product = make_product(session)
        second_product = make_product(session, "SALES-002")
        receive_stock(session, product_id=first_product, quantity=Decimal("5.000"))
        receive_stock(session, product_id=second_product, quantity=Decimal("1.000"))

        with pytest.raises(InsufficientStockError):
            record_sale(
                session,
                SaleCreate(
                    items=[
                        {"product_id": first_product, "quantity": "2.000", "unit_price": "2.00"},
                        {"product_id": second_product, "quantity": "2.000", "unit_price": "3.00"},
                    ]
                ),
            )

    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Sale)) == 0
        assert session.scalar(select(func.count()).select_from(SaleItem)) == 0
        assert session.scalar(select(func.count()).select_from(StockMovement)) == 2
        balances = session.scalars(select(InventoryBalance).order_by(InventoryBalance.product_id)).all()
        assert [balance.quantity_on_hand for balance in balances] == [
            Decimal("5.000"), Decimal("1.000")
        ]


def test_failed_sale_session_can_be_reused_for_a_valid_sale(database):
    _, factory = database
    with factory() as session:
        product = make_product(session)
        receive_stock(session, product_id=product, quantity=Decimal("1.000"))
        with pytest.raises(InsufficientStockError):
            record_sale(
                session,
                SaleCreate(items=[{"product_id": product, "quantity": "2.000", "unit_price": "2.00"}]),
            )

        sale = record_sale(
            session,
            SaleCreate(items=[{"product_id": product, "quantity": "1.000", "unit_price": "2.00"}]),
        )
        assert sale.total_amount == Decimal("2.00")


def test_concurrent_sales_serialize_on_distinct_connections_and_cannot_oversell(database, monkeypatch):
    engine, factory = database
    with factory() as session:
        product_id = make_product(session)
        receive_stock(session, product_id=product_id, quantity=Decimal("5.000"))

    import backend.app.services.sales as sales_service

    first_in_issue = Event()
    second_begin_attempted = Event()
    worker_context = local()
    connection_ids = {}
    original_issue = sales_service.issue_stock_in_transaction

    def observe_begin(connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.strip().upper() == "BEGIN IMMEDIATE":
            connection_ids[worker_context.label] = id(connection)
            if worker_context.label == "second":
                second_begin_attempted.set()

    def hold_first_issue(*args, **kwargs):
        if worker_context.label == "first":
            first_in_issue.set()
            assert second_begin_attempted.wait(timeout=5)
        return original_issue(*args, **kwargs)

    monkeypatch.setattr(sales_service, "issue_stock_in_transaction", hold_first_issue)
    event.listen(engine, "before_cursor_execute", observe_begin)

    def attempt_sale(label):
        worker_context.label = label
        with factory() as session:
            try:
                return record_sale(
                    session,
                    SaleCreate(
                        items=[{"product_id": product_id, "quantity": "4.000", "unit_price": "2.00"}]
                    ),
                ).id
            except InsufficientStockError:
                return "insufficient"

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(attempt_sale, "first")
            assert first_in_issue.wait(timeout=5)
            second = executor.submit(attempt_sale, "second")
            results = [first.result(timeout=10), second.result(timeout=10)]
    finally:
        event.remove(engine, "before_cursor_execute", observe_begin)

    assert connection_ids["first"] != connection_ids["second"]
    assert sum(result != "insufficient" for result in results) == 1
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Sale)) == 1
        assert session.scalar(select(func.count()).select_from(SaleItem)) == 1
        assert session.scalar(
            select(InventoryBalance.quantity_on_hand).where(InventoryBalance.product_id == product_id)
        ) == Decimal("1.000")
        movements = session.scalars(
            select(StockMovement).where(StockMovement.movement_type == "ISSUE")
        ).all()
        items = session.scalars(select(SaleItem)).all()
        assert len(movements) == len(items) == 1
        assert items[0].stock_movement_id == movements[0].id
        assert movements[0].quantity_before == Decimal("5.000")
        assert movements[0].quantity_after == Decimal("1.000")
