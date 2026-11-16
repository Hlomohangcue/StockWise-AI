"""Version 1 sales recording and history endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import AwareDatetime
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.schemas.sales import SaleCreate, SaleListResponse, SaleResponse
from backend.app.services.inventory import (
    InsufficientStockError,
    InventoryBusyError,
    InventoryTransactionConflictError,
    ProductNotFoundError,
)
from backend.app.services.sales import SaleNotFoundError, get_sale, list_sales, record_sale


router = APIRouter(prefix="/sales", tags=["Sales"])


def _raise_sale_conflict() -> None:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Inventory is being updated or the requested stock is unavailable. Retry the operation.",
    )


@router.post("", response_model=SaleResponse, status_code=status.HTTP_201_CREATED)
def create_sale(data: SaleCreate, session: Session = Depends(get_db)) -> SaleResponse:
    try:
        return record_sale(session, data)
    except ProductNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")
    except (InsufficientStockError, InventoryBusyError, InventoryTransactionConflictError):
        _raise_sale_conflict()


@router.get("", response_model=SaleListResponse)
def retrieve_sales(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    product_id: int | None = Query(default=None, ge=1),
    sold_from: AwareDatetime | None = None,
    sold_before: AwareDatetime | None = None,
    session: Session = Depends(get_db),
) -> SaleListResponse:
    if sold_from is not None and sold_before is not None and sold_from >= sold_before:
        raise HTTPException(
            status_code=422,
            detail="sold_from must be earlier than sold_before.",
        )
    try:
        result = list_sales(
            session,
            page=page,
            page_size=page_size,
            product_id=product_id,
            sold_from=sold_from,
            sold_before=sold_before,
        )
    except ProductNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")

    return SaleListResponse(
        items=result.items,
        total=result.total,
        page=page,
        page_size=page_size,
        total_pages=result.total_pages,
        has_next=page < result.total_pages,
        has_previous=page > 1 and result.total_pages > 0,
    )


@router.get("/{sale_id}", response_model=SaleResponse)
def retrieve_sale(sale_id: int, session: Session = Depends(get_db)) -> SaleResponse:
    try:
        return get_sale(session, sale_id)
    except SaleNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sale not found.")
