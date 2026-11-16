"""Sales persistence and history queries."""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from math import ceil

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from backend.app.models import Product, Sale, SaleItem
from backend.app.schemas.sales import SaleCreate
from backend.app.services.inventory import (
    InventoryOperation,
    ProductNotFoundError,
    issue_stock_in_transaction,
    run_inventory_write_transaction,
)


class SaleNotFoundError(Exception):
    """Raised when a requested sale does not exist."""


@dataclass(frozen=True)
class SalePage:
    items: list[Sale]
    total: int
    total_pages: int


CENT = Decimal("0.01")


def _utc_naive(value: datetime) -> datetime:
    """Convert an aware timestamp to UTC for SQLite's timezone-naive storage."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Sale timestamps must include a timezone.")
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _line_total(quantity: Decimal, unit_price: Decimal) -> Decimal:
    return (quantity * unit_price).quantize(CENT, rounding=ROUND_HALF_UP)


def _run_sale_line(
    session: Session,
    *,
    sale_id: int,
    request_line,
    reference: str | None,
) -> Decimal:
    # This shared inventory operation updates the balance and inserts an ISSUE
    # movement without committing the sale's outer BEGIN IMMEDIATE transaction.
    inventory_result: InventoryOperation = issue_stock_in_transaction(
        session,
        product_id=request_line.product_id,
        quantity=request_line.quantity,
        reason="Sale",
        reference=reference,
    )
    movement = inventory_result.movement
    assert movement is not None
    line_total = _line_total(request_line.quantity, request_line.unit_price)
    session.add(
        SaleItem(
            sale_id=sale_id,
            product_id=inventory_result.product.id,
            stock_movement_id=movement.id,
            product_sku=inventory_result.product.sku,
            product_name=inventory_result.product.name,
            quantity=request_line.quantity,
            unit_price=request_line.unit_price,
            line_total=line_total,
        )
    )
    session.flush()
    return line_total


def record_sale(session: Session, data: SaleCreate) -> Sale:
    """Record a multi-item sale atomically with its inventory issue movements."""
    sold_at = _utc_naive(data.sold_at) if data.sold_at is not None else datetime.now(timezone.utc).replace(tzinfo=None)

    def operation() -> int:
        sale = Sale(
            sold_at=sold_at,
            reference=data.reference,
            total_amount=Decimal("0.00"),
        )
        session.add(sale)
        session.flush()

        sale_total = Decimal("0.00")
        for item in data.items:
            sale_total += _run_sale_line(
                session,
                sale_id=sale.id,
                request_line=item,
                reference=data.reference,
            )
        sale.total_amount = sale_total
        session.flush()
        return sale.id

    sale_id = run_inventory_write_transaction(session, operation)
    return get_sale(session, sale_id)


def get_sale(session: Session, sale_id: int) -> Sale:
    sale = session.scalar(
        select(Sale)
        .options(selectinload(Sale.items))
        .where(Sale.id == sale_id)
    )
    if sale is None:
        raise SaleNotFoundError
    return sale


def list_sales(
    session: Session,
    *,
    page: int,
    page_size: int,
    product_id: int | None = None,
    sold_from: datetime | None = None,
    sold_before: datetime | None = None,
) -> SalePage:
    if sold_from is not None and sold_before is not None and sold_from >= sold_before:
        raise ValueError("sold_from must be earlier than sold_before.")

    query = select(Sale).options(selectinload(Sale.items))
    count_query = select(func.count()).select_from(Sale)
    if product_id is not None:
        if session.get(Product, product_id) is None:
            raise ProductNotFoundError
        product_filter = Sale.items.any(SaleItem.product_id == product_id)
        query = query.where(product_filter)
        count_query = count_query.where(product_filter)
    if sold_from is not None:
        start = _utc_naive(sold_from)
        query = query.where(Sale.sold_at >= start)
        count_query = count_query.where(Sale.sold_at >= start)
    if sold_before is not None:
        end = _utc_naive(sold_before)
        query = query.where(Sale.sold_at < end)
        count_query = count_query.where(Sale.sold_at < end)

    total = session.scalar(count_query) or 0
    items = session.scalars(
        query.order_by(Sale.sold_at.desc(), Sale.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return SalePage(list(items), total, ceil(total / page_size) if total else 0)
