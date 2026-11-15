from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Event, local

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base, create_database_engine
from backend.app.models import InventoryBalance, Product, StockMovement
from backend.app.services.inventory import (
    InventoryBusyError,
    InsufficientStockError,
    InventoryTransactionConflictError,
    adjust_stock,
    issue_stock,
    receive_stock,
)
@pytest.fixture
def database(tmp_path):
    database_file = tmp_path / "inventory-service" / "test.db"
    engine = create_database_engine(f"sqlite:///{database_file.as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    try:
        yield engine, factory
    finally:
        engine.dispose()


def make_product(session, *, is_active=True):
    product = Product(
        sku="SERVICE-001",
        name="Service test product",
        unit="kg",
        cost_price=Decimal("1.00"),
        selling_price=Decimal("2.00"),
        reorder_level=0,
        safety_stock=0,
        lead_time_days=0,
        is_active=is_active,
    )
    session.add(product)
    session.flush()
    product_id = product.id
    session.commit()
    return product_id


def test_receive_creates_balance_and_records_before_after_quantities(database):
    _, factory = database
    with factory() as session:
        product = make_product(session)
        first = receive_stock(session, product_id=product, quantity=Decimal("1.125"))
        second = receive_stock(session, product_id=product, quantity=Decimal("0.375"))

        assert first.quantity_on_hand == Decimal("1.125")
        assert first.movement.movement_type == "RECEIVE"
        assert first.movement.quantity_before == Decimal("0.000")
        assert first.movement.quantity_after == Decimal("1.125")
        assert second.quantity_on_hand == Decimal("1.500")
        assert second.movement.quantity_before == Decimal("1.125")
        assert second.movement.quantity_after == Decimal("1.500")
        assert session.scalar(select(func.count()).select_from(InventoryBalance)) == 1


def test_stock_movement_is_allowed_for_inactive_existing_product(database):
    _, factory = database
    with factory() as session:
        product = make_product(session, is_active=False)

        result = receive_stock(session, product_id=product, quantity=Decimal("2.000"))

        assert result.product.is_active is False
        assert result.quantity_on_hand == Decimal("2.000")


def test_issue_decreases_balance_and_can_issue_exact_balance(database):
    _, factory = database
    with factory() as session:
        product = make_product(session)
        receive_stock(session, product_id=product, quantity=Decimal("2.500"))

        result = issue_stock(session, product_id=product, quantity=Decimal("2.500"))

        assert result.quantity_on_hand == Decimal("0.000")
        assert result.movement.movement_type == "ISSUE"
        assert result.movement.quantity_before == Decimal("2.500")
        assert result.movement.quantity_after == Decimal("0.000")


def test_insufficient_issue_rolls_back_without_movement(database):
    _, factory = database
    with factory() as session:
        product = make_product(session)
        receive_stock(session, product_id=product, quantity=Decimal("1.000"))

        with pytest.raises(InsufficientStockError):
            issue_stock(session, product_id=product, quantity=Decimal("1.001"))

        assert session.scalar(
            select(InventoryBalance.quantity_on_hand).where(InventoryBalance.product_id == product)
        ) == Decimal("1.000")
        assert session.scalar(select(func.count()).select_from(StockMovement)) == 1


@pytest.mark.parametrize("quantity", [Decimal("0"), Decimal("-1"), Decimal("1.2345")])
def test_receive_rejects_zero_negative_and_overprecision_quantities(database, quantity):
    _, factory = database
    with factory() as session:
        product = make_product(session)

        with pytest.raises(ValueError):
            receive_stock(session, product_id=product, quantity=quantity)

        assert session.scalar(select(func.count()).select_from(StockMovement)) == 0


def test_adjustment_can_increase_and_decrease_stock(database):
    _, factory = database
    with factory() as session:
        product = make_product(session)
        increased = adjust_stock(
            session,
            product_id=product,
            target_quantity=Decimal("5.250"),
            reason="Opening count",
        )
        decreased = adjust_stock(
            session,
            product_id=product,
            target_quantity=Decimal("4.000"),
            reason="Count correction",
        )

        assert increased.movement.movement_type == "ADJUSTMENT"
        assert increased.movement.quantity == Decimal("5.250")
        assert increased.movement.quantity_before == Decimal("0.000")
        assert increased.movement.quantity_after == Decimal("5.250")
        assert decreased.movement.quantity == Decimal("1.250")
        assert decreased.movement.quantity_before == Decimal("5.250")
        assert decreased.movement.quantity_after == Decimal("4.000")
        assert decreased.movement.reason == "Count correction"


def test_adjustment_rejects_negative_target_and_blank_reason(database):
    _, factory = database
    with factory() as session:
        product = make_product(session)

        with pytest.raises(ValueError):
            adjust_stock(session, product_id=product, target_quantity=Decimal("-0.001"), reason="Count")
        with pytest.raises(ValueError):
            adjust_stock(session, product_id=product, target_quantity=Decimal("1.000"), reason="  ")

        assert session.scalar(select(func.count()).select_from(StockMovement)) == 0


def test_no_op_adjustment_does_not_create_balance_or_movement(database):
    _, factory = database
    with factory() as session:
        product = make_product(session)

        result = adjust_stock(
            session,
            product_id=product,
            target_quantity=Decimal("0.000"),
            reason="Count completed",
        )

        assert result.quantity_on_hand == Decimal("0.000")
        assert result.movement is None
        assert session.scalar(select(func.count()).select_from(InventoryBalance)) == 0
        assert session.scalar(select(func.count()).select_from(StockMovement)) == 0


def test_movement_insert_failure_rolls_back_balance_creation(database):
    engine, factory = database
    with factory() as session:
        product = make_product(session)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TRIGGER fail_movement_insert BEFORE INSERT ON stock_movements "
            "BEGIN SELECT RAISE(ABORT, 'injected movement failure'); END"
        )

    with factory() as session:
        with pytest.raises(IntegrityError):
            receive_stock(session, product_id=product, quantity=Decimal("3.000"))

    with factory() as session:
        assert session.scalar(select(func.count()).select_from(InventoryBalance)) == 0
        assert session.scalar(select(func.count()).select_from(StockMovement)) == 0


def test_balance_update_failure_rolls_back_movement_insert(database):
    engine, factory = database
    with factory() as session:
        product = make_product(session)
        receive_stock(session, product_id=product, quantity=Decimal("3.000"))
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TRIGGER fail_balance_update BEFORE UPDATE ON inventory_balances "
            "BEGIN SELECT RAISE(ABORT, 'injected balance failure'); END"
        )

    with factory() as session:
        with pytest.raises(IntegrityError):
            issue_stock(session, product_id=product, quantity=Decimal("1.000"))

    with factory() as session:
        assert session.scalar(
            select(InventoryBalance.quantity_on_hand).where(InventoryBalance.product_id == product)
        ) == Decimal("3.000")
        assert session.scalar(select(func.count()).select_from(StockMovement)) == 1


def test_concurrent_issues_serialize_and_cannot_overdraw_stock(database):
    _, factory = database
    with factory() as session:
        product = make_product(session)
        receive_stock(session, product_id=product, quantity=Decimal("10.000"))

    start = Event()

    def attempt_issue():
        with factory() as session:
            assert start.wait(timeout=5)
            try:
                issue_stock(session, product_id=product, quantity=Decimal("7.000"))
                return "issued"
            except InsufficientStockError:
                return "insufficient"

    # Both workers leave the start gate together. A separate first-receipt
    # test below holds the first writer lock until the second BEGIN is observed.
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(attempt_issue) for _ in range(2)]
        start.set()
        results = [future.result(timeout=5) for future in futures]

    assert sorted(results) == ["insufficient", "issued"]
    with factory() as session:
        assert session.scalar(
            select(InventoryBalance.quantity_on_hand).where(InventoryBalance.product_id == product)
        ) == Decimal("3.000")
        assert session.scalar(select(func.count()).select_from(StockMovement)) == 2


def test_sqlite_busy_writer_is_reported_as_domain_conflict_and_rolled_back(database):
    engine, factory = database
    with factory() as session:
        product_id = make_product(session)

    short_timeout_engine = create_database_engine(
        engine.url.render_as_string(hide_password=False), sqlite_timeout_seconds=0.05
    )
    short_timeout_factory = sessionmaker(
        bind=short_timeout_engine, autoflush=False, autocommit=False
    )

    lock_connection = engine.connect()
    try:
        lock_connection.exec_driver_sql("BEGIN IMMEDIATE")
        with short_timeout_factory() as session:
            with pytest.raises(InventoryBusyError):
                receive_stock(session, product_id=product_id, quantity=Decimal("1.000"))
    finally:
        lock_connection.rollback()
        lock_connection.close()
        short_timeout_engine.dispose()

    with factory() as session:
        assert session.scalar(select(func.count()).select_from(InventoryBalance)) == 0
        assert session.scalar(select(func.count()).select_from(StockMovement)) == 0


def test_concurrent_first_receipts_use_distinct_connections_and_preserve_sequence(database, monkeypatch):
    engine, factory = database
    with factory() as session:
        product_id = make_product(session)

    import backend.app.services.inventory as inventory_service

    first_writer_in_operation = Event()
    second_begin_attempted = Event()
    worker_context = local()
    connection_ids = {}
    original_get_product = inventory_service._get_product

    def observe_begin(connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.strip().upper() == "BEGIN IMMEDIATE":
            connection_ids[worker_context.name] = id(connection)
            if worker_context.name == "second":
                second_begin_attempted.set()

    def hold_first_writer(session, requested_product_id):
        if worker_context.name == "first":
            first_writer_in_operation.set()
            assert second_begin_attempted.wait(timeout=5)
        return original_get_product(session, requested_product_id)

    monkeypatch.setattr(inventory_service, "_get_product", hold_first_writer)
    event.listen(engine, "before_cursor_execute", observe_begin)

    def receive(label, quantity):
        worker_context.name = label
        with factory() as session:
            result = receive_stock(session, product_id=product_id, quantity=quantity)
            return result.movement

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(receive, "first", Decimal("1.125"))
            assert first_writer_in_operation.wait(timeout=5)
            second = executor.submit(receive, "second", Decimal("0.375"))
            successful_movements = [first.result(timeout=7), second.result(timeout=7)]
    finally:
        event.remove(engine, "before_cursor_execute", observe_begin)

    assert len(connection_ids) == 2
    assert connection_ids["first"] != connection_ids["second"]
    assert all(movement is not None for movement in successful_movements)

    with factory() as session:
        balances = session.scalars(select(InventoryBalance)).all()
        movements = session.scalars(
            select(StockMovement)
            .where(StockMovement.product_id == product_id)
            .order_by(StockMovement.id)
        ).all()
        assert len(balances) == 1
        assert balances[0].quantity_on_hand == Decimal("1.500")
        assert len(movements) == len(successful_movements) == 2
        assert {movement.id for movement in movements} == {
            movement.id for movement in successful_movements
        }
        expected_before = Decimal("0.000")
        for movement in movements:
            assert movement.movement_type == "RECEIVE"
            assert movement.quantity_before == expected_before
            assert movement.quantity_after == expected_before + movement.quantity
            expected_before = movement.quantity_after
        assert expected_before == sum(
            (movement.quantity for movement in successful_movements), Decimal("0.000")
        )


def test_preexisting_session_transaction_is_rolled_back_instead_of_nested(database):
    _, factory = database
    with factory() as session:
        product_id = make_product(session)
        session.scalar(select(Product).where(Product.id == product_id))
        assert session.in_transaction()

        with pytest.raises(InventoryTransactionConflictError):
            receive_stock(session, product_id=product_id, quantity=Decimal("1.000"))

        assert not session.in_transaction()
        assert session.scalar(select(func.count()).select_from(StockMovement)) == 0
