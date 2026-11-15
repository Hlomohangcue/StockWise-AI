"""Product persistence operations and domain errors."""

from math import ceil

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.models import Product
from backend.app.schemas.product import ProductCreate, ProductUpdate


class DuplicateSKUError(Exception):
    """Raised when a product SKU is already in use."""


class ProductNotFoundError(Exception):
    """Raised when a requested product does not exist."""


def _translate_integrity_error(error: IntegrityError) -> None:
    """Translate only SKU uniqueness failures into a domain error."""
    message = str(error.orig).lower()
    if "products.sku" in message or "uq_products_sku" in message:
        raise DuplicateSKUError from error
    raise error


def create_product(session: Session, data: ProductCreate) -> Product:
    product = Product(**data.model_dump())
    session.add(product)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        _translate_integrity_error(error)
    session.refresh(product)
    return product


def list_products(
    session: Session,
    *,
    page: int,
    page_size: int,
    is_active: bool | None,
) -> tuple[list[Product], int, int]:
    query = select(Product)
    count_query = select(func.count()).select_from(Product)
    if is_active is not None:
        query = query.where(Product.is_active.is_(is_active))
        count_query = count_query.where(Product.is_active.is_(is_active))

    total = session.scalar(count_query) or 0
    products = session.scalars(
        query.order_by(Product.id).offset((page - 1) * page_size).limit(page_size)
    ).all()
    total_pages = ceil(total / page_size) if total else 0
    return list(products), total, total_pages


def get_product(session: Session, product_id: int) -> Product:
    product = session.get(Product, product_id)
    if product is None:
        raise ProductNotFoundError
    return product


def update_product(session: Session, product_id: int, data: ProductUpdate) -> Product:
    product = get_product(session, product_id)
    for field_name, value in data.model_dump(exclude_unset=True).items():
        setattr(product, field_name, value)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        _translate_integrity_error(error)
    session.refresh(product)
    return product


def deactivate_product(session: Session, product_id: int) -> Product:
    product = get_product(session, product_id)
    product.is_active = False
    session.commit()
    session.refresh(product)
    return product
