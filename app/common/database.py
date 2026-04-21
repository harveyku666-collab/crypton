"""SQLAlchemy async engine, session factory, and base model."""

from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy import DateTime, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine, AsyncEngine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from datetime import datetime

from app.config import settings


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_db_available: bool = False


def db_available() -> bool:
    return _db_available


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(settings.database_url, echo=settings.debug, pool_size=10)
    return _engine


def async_session() -> AsyncSession:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory()


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    if not _db_available:
        raise RuntimeError("Database not available")
    session = async_session()
    try:
        yield session
    finally:
        await session.close()


async def init_db() -> None:
    global _db_available
    import app.common.models  # noqa: F401

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await _run_migrations(engine)
    _db_available = True


async def _run_migrations(engine: AsyncEngine) -> None:
    """Add columns that may be missing from existing tables."""
    from sqlalchemy import text
    migrations = [
        ("news_items", "sentiment", "VARCHAR(10) DEFAULT 'neutral'"),
        ("news_items", "importance", "VARCHAR(10) DEFAULT 'normal'"),
        ("square_items", "author_id", "VARCHAR(120)"),
        ("square_items", "author_key", "VARCHAR(180)"),
        ("square_items", "is_kol", "INTEGER DEFAULT 0"),
        ("square_items", "matched_kol_name", "VARCHAR(120)"),
        ("square_items", "matched_kol_handle", "VARCHAR(120)"),
        ("square_items", "matched_kol_tier", "VARCHAR(30)"),
        ("whale_alerts", "external_id", "VARCHAR(160)"),
        ("whale_alerts", "event_id", "BIGINT"),
        ("whale_alerts", "blockchain", "VARCHAR(30)"),
        ("whale_alerts", "entity_name", "VARCHAR(160)"),
        ("whale_alerts", "label", "VARCHAR(160)"),
        ("whale_alerts", "amount_usd", "DOUBLE PRECISION"),
        ("whale_alerts", "counterparty_address", "VARCHAR(120)"),
        ("whale_alerts", "severity", "VARCHAR(20)"),
        ("whale_alerts", "notification_status", "VARCHAR(20)"),
        ("whale_alerts", "metadata_json", "JSON"),
    ]
    async with engine.begin() as conn:
        for table, col, col_def in migrations:
            try:
                await conn.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {col_def}")
                )
            except Exception:
                pass


async def close_db() -> None:
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
        _engine = None
        _session_factory = None
