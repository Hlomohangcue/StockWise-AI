from fastapi import FastAPI

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from backend.app.api.v1.products import router as products_router
from backend.app.api.v1.inventory import router as inventory_router
from backend.app.api.v1.sales import router as sales_router
from backend.app.database import Base, engine


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Create any missing MVP tables when the API starts."""
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="StockWise AI API",
    description="Inventory and procurement management API for African SMEs.",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(products_router, prefix="/api/v1")
app.include_router(inventory_router, prefix="/api/v1")
app.include_router(sales_router, prefix="/api/v1")


@app.get("/health", tags=["Health"])
def health_check() -> dict[str, str]:
    """Return the API health status."""
    return {
        "status": "ok",
        "service": "stockwise-api",
    }
