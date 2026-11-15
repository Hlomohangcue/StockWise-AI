from fastapi import FastAPI

app = FastAPI(
    title="StockWise AI API",
    description="Inventory and procurement management API for African SMEs.",
    version="0.1.0",
)


@app.get("/health", tags=["Health"])
def health_check() -> dict[str, str]:
    """Return the API health status."""
    return {
        "status": "ok",
        "service": "stockwise-api",
    }
