"""Request and response schemas for sales recording."""

from datetime import datetime, timezone
from decimal import Decimal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator


class SaleItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    product_id: int = Field(ge=1)
    quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=3)
    # The client must send the actual price; catalogue price is never substituted.
    unit_price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)


class SaleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    items: list[SaleItemCreate] = Field(min_length=1)
    reference: str | None = Field(default=None, max_length=200)
    sold_at: AwareDatetime | None = None


class SaleItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    product_sku: str
    product_name: str
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal
    stock_movement_id: int


class SaleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sold_at: datetime
    reference: str | None
    total_amount: Decimal
    created_at: datetime
    items: list[SaleItemResponse]

    @field_validator("sold_at", "created_at", mode="before")
    @classmethod
    def timestamps_are_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class SaleListResponse(BaseModel):
    items: list[SaleResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_previous: bool
