"""Transactional inventory balance and immutable movement operations.

Movements are allowed for every existing product, including inactive products,
so stock can still be reconciled and historical operations remain traceable.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from math import ceil
from typing import Callable, TypeVar

from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from backend.app.models import InventoryBalance, Product, StockMovement


class ProductNotFoundError(Exception):
    """Raised when an inventory operation references a missing product."""


class InsufficientStockError(Exception):
    """Raised when an issue would make the stock balance negative."""


class InventoryBusyError(Exception):
    """Raised when SQLite cannot acquire its write lock in time."""


class InventoryTransactionConflictError(Exception):
    """Raised if a caller tries to nest an inventory write transaction."""


@dataclass(frozen=True)
class InventoryOperation:
    product: "ProductInventoryInfo"
    quantity_on_hand: Decimal
    movement: "MovementRecord | None"


@dataclass(frozen=True)
class ProductInventoryInfo:
    id: int
    sku: str
    name: str
    unit: str
    is_active: bool


@dataclass(frozen=True)
class MovementRecord:
    id: int
    product_id: int
    movement_type: str
    quantity: Decimal
    quantity_before: Decimal
    quantity_after: Decimal
    reason: str | None
    reference: str | None
    created_at: datetime


@dataclass(frozen=True)
class MovementPage:
    items: list[StockMovement]
    total: int
    total_pages: int


T = TypeVar("T")


def _validate_quantity(quantity: Decimal, *, allow_zero: bool = False) -> None:
    if not isinstance(quantity, Decimal) or not quantity.is_finite():
        raise ValueError("Quantity must be a finite Decimal value.")
    if quantity.as_tuple().exponent < -3:
        raise ValueError("Quantity cannot have more than three decimal places.")
    if quantity < 0 or (quantity == 0 and not allow_zero):
        raise ValueError("Quantity must be positive." if not allow_zero else "Quantity cannot be negative.")
    if quantity >= Decimal("100000000000"):
        raise ValueError("Quantity exceeds the supported precision.")


def _is_sqlite_busy(error: OperationalError) -> bool:
    original = error.orig
    code = getattr(original, "sqlite_errorcode", None)
    if code is not None and code & 0xFF in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
        return True
    message = str(original).lower()
    return "database is locked" in message or "database is busy" in message or "database table is locked" in message


def run_inventory_write_transaction(session: Session, operation: Callable[[], T]) -> T:
    """Run an inventory write as one serialized SQLite transaction.

    The caller must provide a Session with no active transaction. This method
    issues BEGIN IMMEDIATE before reading the balance; balance changes and the
    corresponding movement insert then use the same connection and transaction.
    Every failure rolls back. An already-active transaction is rolled back and
    rejected so this ordering can be guaranteed. SQLite busy/locked failures
    become HTTP 409 at the API boundary; clients may retry after a short delay
    with a bounded retry count. The application does not retry writes.
    """
    if session.in_transaction():
        session.rollback()
        raise InventoryTransactionConflictError

    try:
        connection = session.connection()
        if connection.dialect.name != "sqlite":
            raise RuntimeError("Inventory write locking is configured for SQLite.")

        # The first SQL statement runs before any product/balance read and takes
        # SQLite's reserved writer lock. All following ORM statements in this
        # Session use this same checked-out connection and transaction.
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        result = operation()
        session.commit()
        return result
    except OperationalError as error:
        session.rollback()
        if _is_sqlite_busy(error):
            raise InventoryBusyError from error
        raise
    except BaseException:
        session.rollback()
        raise


def _get_product(session: Session, product_id: int) -> Product:
    product = session.get(Product, product_id)
    if product is None:
        raise ProductNotFoundError
    return product


def _get_or_create_balance(session: Session, product_id: int) -> InventoryBalance:
    balance = session.scalar(
        select(InventoryBalance).where(InventoryBalance.product_id == product_id)
    )
    if balance is None:
        balance = InventoryBalance(product_id=product_id, quantity_on_hand=Decimal("0.000"))
        session.add(balance)
        session.flush()
    return balance


def _new_movement(
    *,
    product_id: int,
    movement_type: str,
    quantity: Decimal,
    before: Decimal,
    after: Decimal,
    reason: str | None,
    reference: str | None,
) -> StockMovement:
    movement = StockMovement(
        product_id=product_id,
        movement_type=movement_type,
        quantity=quantity,
        quantity_before=before,
        quantity_after=after,
        reason=reason,
        reference=reference,
    )
    return movement


def _product_info(product: Product) -> ProductInventoryInfo:
    return ProductInventoryInfo(
        id=product.id,
        sku=product.sku,
        name=product.name,
        unit=product.unit,
        is_active=product.is_active,
    )


def _movement_record(session: Session, movement: StockMovement) -> MovementRecord:
    session.flush()
    session.refresh(movement)
    return MovementRecord(
        id=movement.id,
        product_id=movement.product_id,
        movement_type=movement.movement_type,
        quantity=movement.quantity,
        quantity_before=movement.quantity_before,
        quantity_after=movement.quantity_after,
        reason=movement.reason,
        reference=movement.reference,
        created_at=movement.created_at,
    )


def issue_stock_in_transaction(
    session: Session,
    *,
    product_id: int,
    quantity: Decimal,
    reason: str | None = None,
    reference: str | None = None,
) -> InventoryOperation:
    """Issue stock inside a caller-owned inventory write transaction.

    The caller must run this within ``run_inventory_write_transaction``. This
    function validates and applies the same balance and movement rules as
    ``issue_stock`` but deliberately does not begin, commit, or roll back.
    """
    if not session.in_transaction():
        raise RuntimeError("A caller-owned inventory write transaction is required.")

    _validate_quantity(quantity)
    product = _get_product(session, product_id)
    balance = session.scalar(
        select(InventoryBalance).where(InventoryBalance.product_id == product_id)
    )
    before = balance.quantity_on_hand if balance is not None else Decimal("0.000")
    if quantity > before:
        raise InsufficientStockError

    after = before - quantity
    if balance is None:
        balance = InventoryBalance(product_id=product_id, quantity_on_hand=after)
        session.add(balance)
    else:
        balance.quantity_on_hand = after
    movement = _new_movement(
        product_id=product_id,
        movement_type="ISSUE",
        quantity=quantity,
        before=before,
        after=after,
        reason=reason,
        reference=reference,
    )
    session.add(movement)
    return InventoryOperation(_product_info(product), after, _movement_record(session, movement))


def receive_stock(
    session: Session,
    *,
    product_id: int,
    quantity: Decimal,
    reason: str | None = None,
    reference: str | None = None,
) -> InventoryOperation:
    _validate_quantity(quantity)

    def operation() -> InventoryOperation:
        product = _get_product(session, product_id)
        balance = _get_or_create_balance(session, product_id)
        before = balance.quantity_on_hand
        after = before + quantity
        balance.quantity_on_hand = after
        movement = _new_movement(
            product_id=product_id,
            movement_type="RECEIVE",
            quantity=quantity,
            before=before,
            after=after,
            reason=reason,
            reference=reference,
        )
        session.add(movement)
        return InventoryOperation(_product_info(product), after, _movement_record(session, movement))

    return run_inventory_write_transaction(session, operation)


def issue_stock(
    session: Session,
    *,
    product_id: int,
    quantity: Decimal,
    reason: str | None = None,
    reference: str | None = None,
) -> InventoryOperation:
    _validate_quantity(quantity)

    return run_inventory_write_transaction(
        session,
        lambda: issue_stock_in_transaction(
            session,
            product_id=product_id,
            quantity=quantity,
            reason=reason,
            reference=reference,
        ),
    )


def adjust_stock(
    session: Session,
    *,
    product_id: int,
    target_quantity: Decimal,
    reason: str,
    reference: str | None = None,
) -> InventoryOperation:
    _validate_quantity(target_quantity, allow_zero=True)
    if not reason or not reason.strip():
        raise ValueError("An adjustment reason is required.")

    def operation() -> InventoryOperation:
        product = _get_product(session, product_id)
        balance = session.scalar(
            select(InventoryBalance).where(InventoryBalance.product_id == product_id)
        )
        before = balance.quantity_on_hand if balance is not None else Decimal("0.000")
        if before == target_quantity:
            return InventoryOperation(_product_info(product), before, None)

        if balance is None:
            balance = InventoryBalance(product_id=product_id, quantity_on_hand=target_quantity)
            session.add(balance)
        else:
            balance.quantity_on_hand = target_quantity
        movement = _new_movement(
            product_id=product_id,
            movement_type="ADJUSTMENT",
            quantity=abs(target_quantity - before),
            before=before,
            after=target_quantity,
            reason=reason,
            reference=reference,
        )
        session.add(movement)
        return InventoryOperation(
            _product_info(product),
            target_quantity,
            _movement_record(session, movement),
        )

    return run_inventory_write_transaction(session, operation)


def get_balance(session: Session, product_id: int) -> InventoryOperation:
    product = _get_product(session, product_id)
    balance = session.scalar(select(InventoryBalance).where(InventoryBalance.product_id == product_id))
    quantity = balance.quantity_on_hand if balance is not None else Decimal("0.000")
    return InventoryOperation(_product_info(product), quantity, None)


def list_movements(
    session: Session,
    *,
    page: int,
    page_size: int,
    product_id: int | None = None,
) -> MovementPage:
    query = select(StockMovement)
    count_query = select(func.count()).select_from(StockMovement)
    if product_id is not None:
        _get_product(session, product_id)
        query = query.where(StockMovement.product_id == product_id)
        count_query = count_query.where(StockMovement.product_id == product_id)

    total = session.scalar(count_query) or 0
    items = session.scalars(
        query.order_by(StockMovement.created_at.desc(), StockMovement.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    total_pages = ceil(total / page_size) if total else 0
    return MovementPage(list(items), total, total_pages)


def list_product_movements(
    session: Session,
    *,
    product_id: int,
    page: int,
    page_size: int,
) -> MovementPage:
    return list_movements(session, page=page, page_size=page_size, product_id=product_id)
