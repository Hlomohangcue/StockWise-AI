"""Request and response schemas for inventory operations."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class StockMovementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    product_id: int = Field(ge=1)
    quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=3)
    reason: str | None = Field(default=None, max_length=500)
    reference: str | None = Field(default=None, max_length=200)


class StockAdjustmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    product_id: int = Field(ge=1)
    target_quantity: Decimal = Field(ge=0, max_digits=14, decimal_places=3)
    reason: str = Field(min_length=1, max_length=500)
    reference: str | None = Field(default=None, max_length=200)


class InventoryBalanceResponse(BaseModel):
    product_id: int
    sku: str
    name: str
    unit: str
    quantity_on_hand: Decimal


class StockMovementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    movement_type: str
    quantity: Decimal
    quantity_before: Decimal
    quantity_after: Decimal
    reason: str | None
    reference: str | None
    created_at: datetime


class InventoryOperationResponse(BaseModel):
    balance: InventoryBalanceResponse
    movement: StockMovementResponse | None


class StockMovementListResponse(BaseModel):
    items: list[StockMovementResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_previous: bool
