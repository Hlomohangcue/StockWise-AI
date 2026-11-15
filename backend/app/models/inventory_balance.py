"""Current stock balance for a product."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.database import Base


class InventoryBalance(Base):
    __tablename__ = "inventory_balances"
    __table_args__ = (
        UniqueConstraint("product_id", name="uq_inventory_balances_product_id"),
        CheckConstraint("quantity_on_hand >= 0", name="ck_inventory_balances_quantity_nonnegative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    quantity_on_hand: Mapped[Decimal] = mapped_column(
        Numeric(14, 3), nullable=False, default=Decimal("0.000"), server_default="0.000"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )
