from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base, create_database_engine
from backend.app.models import InventoryBalance, Product, StockMovement


@pytest.fixture
def database(tmp_path):
    database_file = tmp_path / "inventory-models" / "test.db"
    engine = create_database_engine(f"sqlite:///{database_file.as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    try:
        yield factory
    finally:
        engine.dispose()


def add_product(session) -> Product:
    product = Product(
        sku="MODEL-001",
        name="Model test product",
        unit="kg",
        cost_price=Decimal("1.00"),
        selling_price=Decimal("2.00"),
        reorder_level=0,
        safety_stock=0,
        lead_time_days=0,
    )
    session.add(product)
    session.commit()
    return product


def test_inventory_balance_allows_only_one_row_per_product(database):
    with database() as session:
        product = add_product(session)
        session.add_all(
            [
                InventoryBalance(product_id=product.id, quantity_on_hand=Decimal("1.000")),
                InventoryBalance(product_id=product.id, quantity_on_hand=Decimal("2.000")),
            ]
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_inventory_balance_rejects_negative_quantity(database):
    with database() as session:
        product = add_product(session)
        session.add(InventoryBalance(product_id=product.id, quantity_on_hand=Decimal("-0.001")))
        with pytest.raises(IntegrityError):
            session.commit()


def test_inventory_balance_enforces_product_foreign_key(database):
    with database() as session:
        session.add(InventoryBalance(product_id=999, quantity_on_hand=Decimal("0.000")))
        with pytest.raises(IntegrityError):
            session.commit()


@pytest.mark.parametrize("quantity", [Decimal("0.000"), Decimal("-0.001")])
def test_stock_movement_requires_positive_quantity(database, quantity):
    with database() as session:
        product = add_product(session)
        session.add(
            StockMovement(
                product_id=product.id,
                movement_type="RECEIVE",
                quantity=quantity,
                quantity_before=Decimal("0.000"),
                quantity_after=Decimal("1.000"),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


@pytest.mark.parametrize(
    ("before", "after"),
    [(Decimal("-0.001"), Decimal("0.000")), (Decimal("0.000"), Decimal("-0.001"))],
)
def test_stock_movement_rejects_negative_before_or_after(database, before, after):
    with database() as session:
        product = add_product(session)
        session.add(
            StockMovement(
                product_id=product.id,
                movement_type="RECEIVE",
                quantity=Decimal("1.000"),
                quantity_before=before,
                quantity_after=after,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_stock_movement_enforces_product_foreign_key(database):
    with database() as session:
        session.add(
            StockMovement(
                product_id=999,
                movement_type="RECEIVE",
                quantity=Decimal("1.000"),
                quantity_before=Decimal("0.000"),
                quantity_after=Decimal("1.000"),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


@pytest.mark.parametrize(
    ("movement_type", "quantity", "before", "after"),
    [
        ("RECEIVE", Decimal("1.000"), Decimal("0.000"), Decimal("0.999")),
        ("ISSUE", Decimal("1.000"), Decimal("2.000"), Decimal("1.001")),
        ("ADJUSTMENT", Decimal("1.000"), Decimal("0.000"), Decimal("1.001")),
    ],
)
def test_stock_movement_rejects_invalid_type_arithmetic(database, movement_type, quantity, before, after):
    with database() as session:
        product = add_product(session)
        session.add(
            StockMovement(
                product_id=product.id,
                movement_type=movement_type,
                quantity=quantity,
                quantity_before=before,
                quantity_after=after,
                reason="Count correction" if movement_type == "ADJUSTMENT" else None,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_stock_movement_rejects_noop_adjustment(database):
    with database() as session:
        product = add_product(session)
        session.add(
            StockMovement(
                product_id=product.id,
                movement_type="ADJUSTMENT",
                quantity=Decimal("0.001"),
                quantity_before=Decimal("1.000"),
                quantity_after=Decimal("1.000"),
                reason="Count confirmed",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


@pytest.mark.parametrize(
    ("quantity", "quantity_before", "quantity_after"),
    [
        ("1.0004", "0.000", "1.0004"),
        ("1.000", "0.0004", "1.000"),
        ("1.000", "0.000", "1.0004"),
    ],
    ids=["quantity", "quantity_before", "quantity_after"],
)
def test_sqlite_rejects_excess_precision_in_movement_columns(
    database, quantity, quantity_before, quantity_after
):
    with database() as session:
        product = add_product(session)
        with pytest.raises(IntegrityError):
            session.execute(
                text(
                    "INSERT INTO stock_movements "
                    "(product_id, movement_type, quantity, quantity_before, quantity_after) "
                    "VALUES (:product_id, 'RECEIVE', :quantity, :quantity_before, :quantity_after)"
                ),
                {
                    "product_id": product.id,
                    "quantity": quantity,
                    "quantity_before": quantity_before,
                    "quantity_after": quantity_after,
                },
            )


def test_sqlite_accepts_valid_three_decimal_movement_values(database):
    with database() as session:
        product = add_product(session)
        movements = [
            ("1", "0", "1"),
            ("1.125", "1", "2.125"),
            ("0.001", "2.125", "2.126"),
        ]
        for quantity, before, after in movements:
            session.execute(
                text(
                    "INSERT INTO stock_movements "
                    "(product_id, movement_type, quantity, quantity_before, quantity_after) "
                    "VALUES (:product_id, 'RECEIVE', :quantity, :quantity_before, :quantity_after)"
                ),
                {
                    "product_id": product.id,
                    "quantity": quantity,
                    "quantity_before": before,
                    "quantity_after": after,
                },
            )
        session.commit()

        assert session.execute(text("SELECT COUNT(*) FROM stock_movements")).scalar_one() == 3


def test_stock_movement_rejects_unknown_movement_type(database):
    with database() as session:
        product = add_product(session)
        session.add(
            StockMovement(
                product_id=product.id,
                movement_type="TRANSFER",
                quantity=Decimal("1.000"),
                quantity_before=Decimal("0.000"),
                quantity_after=Decimal("1.000"),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_adjustment_movement_requires_reason(database):
    with database() as session:
        product = add_product(session)
        session.add(
            StockMovement(
                product_id=product.id,
                movement_type="ADJUSTMENT",
                quantity=Decimal("1.000"),
                quantity_before=Decimal("0.000"),
                quantity_after=Decimal("1.000"),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
