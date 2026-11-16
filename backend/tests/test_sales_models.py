from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base, create_database_engine
from backend.app.models import Product, Sale, SaleItem, StockMovement


@pytest.fixture
def database(tmp_path):
    database_file = tmp_path / "sales-models" / "test.db"
    engine = create_database_engine(f"sqlite:///{database_file.as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    try:
        yield factory
    finally:
        engine.dispose()


def make_records(session):
    product = Product(
        sku="SALE-MODEL-001",
        name="Model sale product",
        unit="item",
        cost_price=Decimal("1.00"),
        selling_price=Decimal("2.00"),
        reorder_level=0,
        safety_stock=0,
        lead_time_days=0,
    )
    session.add(product)
    session.commit()

    sale = Sale(
        sold_at=datetime(2025, 1, 1, 10, 0),
        total_amount=Decimal("2.25"),
    )
    movement = StockMovement(
        product_id=product.id,
        movement_type="ISSUE",
        quantity=Decimal("1.125"),
        quantity_before=Decimal("2.000"),
        quantity_after=Decimal("0.875"),
    )
    session.add_all([sale, movement])
    session.commit()
    return product, sale, movement


def test_sale_item_preserves_product_snapshot_and_links_issue_movement(database):
    with database() as session:
        product, sale, movement = make_records(session)
        item = SaleItem(
            sale_id=sale.id,
            product_id=product.id,
            stock_movement_id=movement.id,
            product_sku=product.sku,
            product_name=product.name,
            quantity=Decimal("1.125"),
            unit_price=Decimal("2.00"),
            line_total=Decimal("2.25"),
        )
        session.add(item)
        session.commit()
        session.refresh(item)

        assert item.sale_id == sale.id
        assert item.product_id == product.id
        assert item.stock_movement_id == movement.id
        assert item.quantity == Decimal("1.125")
        assert item.product_name == "Model sale product"


@pytest.mark.parametrize(
    ("quantity", "unit_price", "line_total"),
    [
        ("1.0004", "2.00", "2.00"),
        ("1.000", "2.001", "2.00"),
        ("1.000", "2.00", "2.01"),
    ],
    ids=["quantity-scale", "price-scale", "line-total-arithmetic"],
)
def test_sale_item_database_constraints_reject_invalid_money_or_quantity(
    database, quantity, unit_price, line_total
):
    with database() as session:
        product, sale, movement = make_records(session)
        with pytest.raises(IntegrityError):
            session.execute(
                text(
                    "INSERT INTO sale_items "
                    "(sale_id, product_id, stock_movement_id, product_sku, product_name, "
                    "quantity, unit_price, line_total) "
                    "VALUES (:sale_id, :product_id, :movement_id, :sku, :name, "
                    ":quantity, :unit_price, :line_total)"
                ),
                {
                    "sale_id": sale.id,
                    "product_id": product.id,
                    "movement_id": movement.id,
                    "sku": product.sku,
                    "name": product.name,
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "line_total": line_total,
                },
            )


def test_sale_item_rejects_reuse_of_a_stock_movement(database):
    with database() as session:
        product, sale, movement = make_records(session)
        session.add(
            SaleItem(
                sale_id=sale.id,
                product_id=product.id,
                stock_movement_id=movement.id,
                product_sku=product.sku,
                product_name=product.name,
                quantity=Decimal("1.125"),
                unit_price=Decimal("2.00"),
                line_total=Decimal("2.25"),
            )
        )
        session.commit()
        session.add(
            SaleItem(
                sale_id=sale.id,
                product_id=product.id,
                stock_movement_id=movement.id,
                product_sku=product.sku,
                product_name=product.name,
                quantity=Decimal("1.125"),
                unit_price=Decimal("2.00"),
                line_total=Decimal("2.25"),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
