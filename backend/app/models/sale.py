"""Sales headers and immutable product lines."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.database import Base


class Sale(Base):
    __tablename__ = "sales"
    __table_args__ = (
        CheckConstraint("total_amount >= 0", name="ck_sales_total_nonnegative"),
        CheckConstraint("total_amount = round(total_amount, 2)", name="ck_sales_total_scale"),
        Index("ix_sales_sold_at_id", "sold_at", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # SQLite stores UTC as a timezone-naive timestamp; service and schemas
    # normalize inputs to UTC and serialize responses with a UTC offset.
    sold_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    reference: Mapped[str | None] = mapped_column(String(200), nullable=True)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(26, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    items: Mapped[list["SaleItem"]] = relationship(
        back_populates="sale", order_by="SaleItem.id"
    )


class SaleItem(Base):
    __tablename__ = "sale_items"
    __table_args__ = (
        UniqueConstraint("stock_movement_id", name="uq_sale_items_stock_movement_id"),
        CheckConstraint("quantity > 0", name="ck_sale_items_quantity_positive"),
        CheckConstraint("quantity = round(quantity, 3)", name="ck_sale_items_quantity_scale"),
        CheckConstraint("unit_price >= 0", name="ck_sale_items_unit_price_nonnegative"),
        CheckConstraint("unit_price = round(unit_price, 2)", name="ck_sale_items_unit_price_scale"),
        CheckConstraint("line_total >= 0", name="ck_sale_items_line_total_nonnegative"),
        CheckConstraint("line_total = round(line_total, 2)", name="ck_sale_items_line_total_scale"),
        CheckConstraint(
            # Quantity and price are scale-checked above. A tiny epsilon before
            # SQLite ROUND compensates only for binary-float representation at
            # exact half-cent boundaries, matching Python ROUND_HALF_UP.
            "line_total = round(quantity * unit_price + 0.000000001, 2)",
            name="ck_sale_items_line_total_matches_quantity_price",
        ),
        Index("ix_sale_items_sale_id_id", "sale_id", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sale_id: Mapped[int] = mapped_column(
        ForeignKey("sales.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    stock_movement_id: Mapped[int] = mapped_column(
        ForeignKey("stock_movements.id", ondelete="RESTRICT"), nullable=False
    )
    product_sku: Mapped[str] = mapped_column(String(100), nullable=False)
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(24, 2), nullable=False)

    sale: Mapped[Sale] = relationship(back_populates="items")
