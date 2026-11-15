"""Version 1 inventory movement endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.schemas.inventory import (
    InventoryBalanceResponse,
    InventoryOperationResponse,
    StockAdjustmentRequest,
    StockMovementListResponse,
    StockMovementRequest,
)
from backend.app.services.inventory import (
    InsufficientStockError,
    InventoryBusyError,
    InventoryTransactionConflictError,
    ProductNotFoundError,
    adjust_stock,
    get_balance,
    issue_stock,
    list_movements,
    list_product_movements,
    receive_stock,
)


router = APIRouter(
    prefix="/inventory",
    tags=["Inventory"],
)


def _operation_response(result) -> InventoryOperationResponse:
    return InventoryOperationResponse(
        balance=InventoryBalanceResponse(
            product_id=result.product.id,
            sku=result.product.sku,
            name=result.product.name,
            unit=result.product.unit,
            quantity_on_hand=result.quantity_on_hand,
        ),
        movement=result.movement,
    )


def _raise_not_found() -> None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")


def _raise_inventory_conflict() -> None:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Inventory is being updated or the requested stock is unavailable. Retry the operation.",
    )


@router.post(
    "/receive",
    response_model=InventoryOperationResponse,
    status_code=status.HTTP_201_CREATED,
    description="Receive stock for any existing product, including inactive products.",
)
def receive_inventory(data: StockMovementRequest, session: Session = Depends(get_db)):
    try:
        result = receive_stock(
            session,
            product_id=data.product_id,
            quantity=data.quantity,
            reason=data.reason,
            reference=data.reference,
        )
    except ProductNotFoundError:
        _raise_not_found()
    except (InventoryBusyError, InventoryTransactionConflictError):
        _raise_inventory_conflict()
    return _operation_response(result)


@router.post(
    "/issue",
    response_model=InventoryOperationResponse,
    status_code=status.HTTP_201_CREATED,
    description="Issue stock for any existing product, including inactive products.",
)
def issue_inventory(data: StockMovementRequest, session: Session = Depends(get_db)):
    try:
        result = issue_stock(
            session,
            product_id=data.product_id,
            quantity=data.quantity,
            reason=data.reason,
            reference=data.reference,
        )
    except ProductNotFoundError:
        _raise_not_found()
    except InsufficientStockError:
        _raise_inventory_conflict()
    except (InventoryBusyError, InventoryTransactionConflictError):
        _raise_inventory_conflict()
    return _operation_response(result)


@router.post(
    "/adjustments",
    response_model=InventoryOperationResponse,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Set a target stock quantity. The movement quantity is the positive magnitude; "
        "before/after balances indicate increase or decrease. Works for inactive products."
    ),
)
def adjust_inventory(
    data: StockAdjustmentRequest,
    response: Response,
    session: Session = Depends(get_db),
):
    try:
        result = adjust_stock(
            session,
            product_id=data.product_id,
            target_quantity=data.target_quantity,
            reason=data.reason,
            reference=data.reference,
        )
    except ProductNotFoundError:
        _raise_not_found()
    except (InventoryBusyError, InventoryTransactionConflictError):
        _raise_inventory_conflict()
    if result.movement is None:
        response.status_code = status.HTTP_200_OK
    return _operation_response(result)


@router.get("/{product_id}/balance", response_model=InventoryBalanceResponse)
def retrieve_inventory_balance(product_id: int, session: Session = Depends(get_db)):
    try:
        result = get_balance(session, product_id)
    except ProductNotFoundError:
        _raise_not_found()
    return InventoryBalanceResponse(
        product_id=result.product.id,
        sku=result.product.sku,
        name=result.product.name,
        unit=result.product.unit,
        quantity_on_hand=result.quantity_on_hand,
    )


@router.get("/movements", response_model=StockMovementListResponse)
def retrieve_all_movements(
    product_id: int | None = Query(default=None, ge=1),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_db),
):
    try:
        movement_page = list_movements(
            session,
            page=page,
            page_size=page_size,
            product_id=product_id,
        )
    except ProductNotFoundError:
        _raise_not_found()
    return _movement_list_response(movement_page, page, page_size)


@router.get("/{product_id}/movements", response_model=StockMovementListResponse)
def retrieve_product_movements(
    product_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_db),
):
    try:
        movement_page = list_product_movements(
            session,
            product_id=product_id,
            page=page,
            page_size=page_size,
        )
    except ProductNotFoundError:
        _raise_not_found()
    return _movement_list_response(movement_page, page, page_size)


def _movement_list_response(page, page_number: int, page_limit: int) -> StockMovementListResponse:
    return StockMovementListResponse(
        items=page.items,
        total=page.total,
        page=page_number,
        page_size=page_limit,
        total_pages=page.total_pages,
        has_next=page_number < page.total_pages,
        has_previous=page_number > 1 and page.total_pages > 0,
    )
