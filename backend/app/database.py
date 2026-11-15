"""SQLAlchemy database configuration and FastAPI session dependency."""

import os
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE_URL = f"sqlite:///{(PROJECT_ROOT / 'backend' / 'data' / 'stockwise.db').as_posix()}"
DATABASE_URL_ENV = "DATABASE_URL"
SQLITE_TIMEOUT_SECONDS = 10


class Base(DeclarativeBase):
    """Base class for application ORM models."""


def create_database_engine(
    database_url: str,
    *,
    sqlite_timeout_seconds: float = SQLITE_TIMEOUT_SECONDS,
) -> Engine:
    """Create an engine and prepare parent directories for file-based SQLite.

    SQLite connections wait up to 10 seconds by default before reporting a
    busy/locked error. Inventory endpoints translate that to HTTP 409. Clients
    may retry after a short delay with a bounded retry count; writes are never
    automatically retried by the application.
    """
    connect_args: dict[str, object] = {}
    engine_options: dict[str, object] = {}

    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        connect_args["timeout"] = sqlite_timeout_seconds
        if database_url in ("sqlite://", "sqlite:///:memory:"):
            # Share an in-memory database between sessions/connections.
            engine_options["poolclass"] = StaticPool
        else:
            database_path = Path(database_url.removeprefix("sqlite:///"))
            if not database_path.is_absolute():
                database_path = PROJECT_ROOT / database_path
            database_path.parent.mkdir(parents=True, exist_ok=True)

    database_engine = create_engine(
        database_url,
        connect_args=connect_args,
        **engine_options,
    )
    if database_url.startswith("sqlite"):
        event.listen(database_engine, "connect", _enable_sqlite_foreign_keys)
    return database_engine


def _enable_sqlite_foreign_keys(connection, _connection_record) -> None:
    """Enable SQLite foreign-key checks on each new DBAPI connection."""
    cursor = connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


DATABASE_URL = os.getenv(DATABASE_URL_ENV, DEFAULT_DATABASE_URL)
engine = create_database_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    """Yield a request-scoped database session and always close it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
