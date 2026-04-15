"""ORM models for all domain tables."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Float, Index, Integer, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.common.database import Base, TimestampMixin


class PriceTick(TimestampMixin, Base):
    __tablename__ = "price_ticks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    price: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float, default=0)
    change_pct: Mapped[float] = mapped_column(Float, default=0)
    source: Mapped[str] = mapped_column(String(30), default="desk3")

    __table_args__ = (Index("ix_price_symbol_ts", "symbol", "created_at"),)


class KlineData(TimestampMixin, Base):
    __tablename__ = "kline_data"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    interval: Mapped[str] = mapped_column(String(10))
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)
    ts: Mapped[datetime] = mapped_column(index=True)

    __table_args__ = (Index("ix_kline_sym_int_ts", "symbol", "interval", "ts"),)


class Indicator(TimestampMixin, Base):
    __tablename__ = "indicators"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    indicator_type: Mapped[str] = mapped_column(String(50))
    value: Mapped[float] = mapped_column(Float)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)


class NewsItem(TimestampMixin, Base):
    __tablename__ = "news_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(500))
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(50))
    category: Mapped[str] = mapped_column(String(30), index=True)
    language: Mapped[str] = mapped_column(String(10), index=True, default="en")
    sentiment: Mapped[str] = mapped_column(String(10), index=True, default="neutral")
    importance: Mapped[str] = mapped_column(String(10), index=True, default="normal")
    published_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, unique=True)

    __table_args__ = (Index("ix_news_lang_cat", "language", "category"),)


class FundingRate(TimestampMixin, Base):
    __tablename__ = "funding_rates"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    rate: Mapped[float] = mapped_column(Float)
    predicted_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volume_24h: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class DefiYield(TimestampMixin, Base):
    __tablename__ = "defi_yields"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    pool: Mapped[str] = mapped_column(String(100))
    project: Mapped[str] = mapped_column(String(50), index=True)
    chain: Mapped[str] = mapped_column(String(30))
    symbol: Mapped[str] = mapped_column(String(50))
    apy: Mapped[float] = mapped_column(Float)
    tvl: Mapped[float] = mapped_column(Float, default=0)


class Prediction(TimestampMixin, Base):
    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    direction: Mapped[str] = mapped_column(String(10))
    confidence: Mapped[float] = mapped_column(Float)
    model: Mapped[str] = mapped_column(String(50))
    reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    actual_result: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)


class TradeLog(TimestampMixin, Base):
    __tablename__ = "trade_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    exchange: Mapped[str] = mapped_column(String(20))
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    side: Mapped[str] = mapped_column(String(10))
    price: Mapped[float] = mapped_column(Float)
    quantity: Mapped[float] = mapped_column(Float)
    pnl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    strategy: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)


class WhaleAlert(TimestampMixin, Base):
    __tablename__ = "whale_alerts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    address: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(20))
    amount: Mapped[float] = mapped_column(Float)
    token: Mapped[str] = mapped_column(String(20))
    tx_hash: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)


class Briefing(TimestampMixin, Base):
    __tablename__ = "briefings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    period: Mapped[str] = mapped_column(String(20), index=True)
    language: Mapped[str] = mapped_column(String(10), index=True, default="zh")
    title: Mapped[str] = mapped_column(String(200))
    content_json: Mapped[dict] = mapped_column(JSON)
    content_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_briefing_period_lang", "period", "language", "created_at"),)


class AIDecision(TimestampMixin, Base):
    __tablename__ = "ai_decisions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    input_features: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    decision: Mapped[str] = mapped_column(String(20))
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
