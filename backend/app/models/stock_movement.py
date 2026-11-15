"""Immutable inventory movement history."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.database import Base


class StockMovement(Base):
    __tablename__ = "stock_movements"
    __table_args__ = (
        CheckConstraint(
            "movement_type IN ('RECEIVE', 'ISSUE', 'ADJUSTMENT')",
            name="ck_stock_movements_type_valid",
        ),
        CheckConstraint("quantity > 0", name="ck_stock_movements_quantity_positive"),
        CheckConstraint("quantity_before >= 0", name="ck_stock_movements_before_nonnegative"),
        CheckConstraint("quantity_after >= 0", name="ck_stock_movements_after_nonnegative"),
        CheckConstraint(
            "quantity = round(quantity, 3)",
            name="ck_stock_movements_quantity_scale",
        ),
        CheckConstraint(
            "quantity_before = round(quantity_before, 3)",
            name="ck_stock_movements_before_scale",
        ),
        CheckConstraint(
            "quantity_after = round(quantity_after, 3)",
            name="ck_stock_movements_after_scale",
        ),
        # SQLite stores NUMERIC values using integer/float affinity. The scale
        # checks above reject excess precision; rounding only arithmetic
        # comparisons avoids binary-float equality artifacts without rounding
        # the stored movement values.
        CheckConstraint(
            "movement_type != 'RECEIVE' OR "
            "round(quantity_after, 3) = round(quantity_before + quantity, 3)",
            name="ck_stock_movements_receive_arithmetic",
        ),
        CheckConstraint(
            "movement_type != 'ISSUE' OR "
            "round(quantity_before, 3) = round(quantity_after + quantity, 3)",
            name="ck_stock_movements_issue_arithmetic",
        ),
        CheckConstraint(
            "movement_type != 'ADJUSTMENT' OR "
            "(quantity_before != quantity_after AND "
            "round(quantity, 3) = round(abs(quantity_after - quantity_before), 3))",
            name="ck_stock_movements_adjustment_arithmetic",
        ),
        CheckConstraint(
            "movement_type != 'ADJUSTMENT' OR "
            "(reason IS NOT NULL AND length(trim(reason)) > 0)",
            name="ck_stock_movements_adjustment_reason_required",
        ),
        Index("ix_stock_movements_created_at_id", "created_at", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    movement_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # Quantity is always a positive magnitude. For adjustments, the signed
    # direction is represented by quantity_after relative to quantity_before.
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    quantity_before: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    quantity_after: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reference: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())
