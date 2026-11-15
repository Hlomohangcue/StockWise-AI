from datetime import datetime
from decimal import Decimal
import os
import subprocess
import sys
import time

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base, create_database_engine
from backend.app.models import Product


@pytest.fixture
def database(tmp_path):
    database_file = tmp_path / "isolated" / "test.db"
    test_engine = create_database_engine(f"sqlite:///{database_file.as_posix()}")
    Base.metadata.create_all(test_engine)
    factory = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)
    try:
        yield test_engine, factory
    finally:
        test_engine.dispose()


def product_values(**overrides):
    values = {
        "sku": "SKU-001",
        "name": "Tea",
        "unit": "box",
        "cost_price": Decimal("1.25"),
        "selling_price": Decimal("2.50"),
        "reorder_level": 5,
        "safety_stock": 2,
        "lead_time_days": 3,
    }
    values.update(overrides)
    return values


def test_database_initialization_creates_tables_and_parent_directory(tmp_path):
    db_file = tmp_path / "nested" / "app.db"
    test_engine = create_database_engine(f"sqlite:///{db_file.as_posix()}")
    try:
        Base.metadata.create_all(test_engine)

        assert db_file.exists()
        assert "products" in inspect(test_engine).get_table_names()
    finally:
        test_engine.dispose()


def test_database_url_environment_override_configures_application_engine(tmp_path):
    database_file = tmp_path / "override.db"
    database_url = f"sqlite:///{database_file.as_posix()}"
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    environment["EXPECTED_DATABASE"] = database_file.as_posix()
    check_engine_configuration = (
        "import os; from pathlib import Path; "
        "from backend.app.database import DATABASE_URL, engine; "
        "assert DATABASE_URL == os.environ['DATABASE_URL']; "
        "assert Path(engine.url.database).resolve() == Path(os.environ['EXPECTED_DATABASE']).resolve(); "
        "connection = engine.connect(); connection.close()"
    )

    subprocess.run(
        [sys.executable, "-c", check_engine_configuration],
        cwd=project_root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    assert database_file.exists()


def test_product_can_be_created_with_decimal_prices_and_timestamps(database):
    _, factory = database
    with factory() as session:
        product = Product(**product_values())
        session.add(product)
        session.commit()
        session.refresh(product)

        assert product.id is not None
        assert product.cost_price == Decimal("1.25")
        assert product.selling_price == Decimal("2.50")
        assert product.is_active is True
        assert isinstance(product.created_at, datetime)
        assert isinstance(product.updated_at, datetime)


def test_updated_at_advances_when_product_changes(database):
    _, factory = database
    with factory() as session:
        product = Product(**product_values())
        session.add(product)
        session.commit()
        session.refresh(product)
        created_at = product.created_at
        updated_at = product.updated_at

        # SQLite CURRENT_TIMESTAMP has second precision; cross its boundary so
        # the timestamp comparison does not depend on sub-second timing.
        time.sleep(1.1)
        product.name = "Green tea"
        session.commit()
        session.refresh(product)

        assert product.updated_at > updated_at
        assert product.created_at == created_at


@pytest.mark.parametrize("field", ["sku", "name"])
def test_required_product_fields_reject_null_values(database, field):
    _, factory = database
    with factory() as session:
        session.add(Product(**product_values(**{field: None})))
        with pytest.raises(IntegrityError):
            session.commit()


def test_sku_must_be_unique(database):
    _, factory = database
    with factory() as session:
        session.add(Product(**product_values()))
        session.commit()
        session.add(Product(**product_values(name="Different item")))
        with pytest.raises(IntegrityError):
            session.commit()


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("cost_price", Decimal("-0.01")),
        ("selling_price", Decimal("-0.01")),
        ("reorder_level", -1),
        ("safety_stock", -1),
        ("lead_time_days", -1),
    ],
)
def test_nonnegative_product_fields_are_enforced_by_database(database, field, invalid_value):
    _, factory = database
    with factory() as session:
        session.add(Product(**product_values(**{field: invalid_value})))
        with pytest.raises(IntegrityError):
            session.commit()


def test_required_sku_and_name_cannot_be_empty(database):
    _, factory = database
    with factory() as session:
        session.add(Product(**product_values(sku="")))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        session.add(Product(**product_values(name="")))
        with pytest.raises(IntegrityError):
            session.commit()


@pytest.mark.parametrize("unit", ["", None])
def test_required_unit_rejects_empty_and_null_values(database, unit):
    _, factory = database
    with factory() as session:
        session.add(Product(**product_values(unit=unit)))
        with pytest.raises(IntegrityError):
            session.commit()


def test_each_test_database_is_isolated(database):
    _, factory = database
    with factory() as session:
        assert session.query(Product).count() == 0
