"""Version 1 product endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.schemas.product import ProductCreate, ProductListResponse, ProductResponse, ProductUpdate
from backend.app.services.products import (
    DuplicateSKUError,
    ProductNotFoundError,
    create_product,
    deactivate_product,
    get_product,
    list_products,
    update_product,
)


router = APIRouter(prefix="/products", tags=["Products"])


@router.post("", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
def create_product_endpoint(data: ProductCreate, session: Session = Depends(get_db)) -> ProductResponse:
    try:
        return create_product(session, data)
    except DuplicateSKUError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A product with this SKU already exists.")


@router.get("", response_model=ProductListResponse)
def list_products_endpoint(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    is_active: bool | None = Query(default=None),
    session: Session = Depends(get_db),
) -> ProductListResponse:
    items, total, total_pages = list_products(
        session,
        page=page,
        page_size=page_size,
        is_active=is_active,
    )
    return ProductListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_previous=page > 1 and total_pages > 0,
    )


@router.get("/{product_id}", response_model=ProductResponse)
def retrieve_product_endpoint(product_id: int, session: Session = Depends(get_db)) -> ProductResponse:
    try:
        return get_product(session, product_id)
    except ProductNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")


@router.patch("/{product_id}", response_model=ProductResponse)
def update_product_endpoint(
    product_id: int,
    data: ProductUpdate,
    session: Session = Depends(get_db),
) -> ProductResponse:
    try:
        return update_product(session, product_id, data)
    except ProductNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")
    except DuplicateSKUError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A product with this SKU already exists.")


@router.delete("/{product_id}", response_model=ProductResponse)
def deactivate_product_endpoint(product_id: int, session: Session = Depends(get_db)) -> ProductResponse:
    try:
        return deactivate_product(session, product_id)
    except ProductNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")
