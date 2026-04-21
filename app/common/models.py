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


class SquareItem(TimestampMixin, Base):
    __tablename__ = "square_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(20), index=True)
    channel: Mapped[str] = mapped_column(String(20), index=True, default="square")
    item_type: Mapped[str] = mapped_column(String(20), index=True, default="post")
    title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    author_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    author_key: Mapped[Optional[str]] = mapped_column(String(180), index=True, nullable=True)
    author_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    author_handle: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    is_kol: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    matched_kol_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    matched_kol_handle: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    matched_kol_tier: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    language: Mapped[Optional[str]] = mapped_column(String(20), index=True, nullable=True)
    published_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(150), nullable=True, unique=True)
    engagement_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    symbols_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    tags_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_square_platform_created", "platform", "created_at"),
        Index("ix_square_platform_type", "platform", "item_type"),
        Index("ix_square_author_window", "platform", "author_key", "created_at"),
    )


class SquareKOLProfile(TimestampMixin, Base):
    __tablename__ = "square_kol_profiles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(20), index=True)
    name: Mapped[str] = mapped_column(String(120))
    handle: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    author_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    aliases_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    tier: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_active: Mapped[int] = mapped_column(Integer, default=1, index=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_square_kol_platform_handle", "platform", "handle"),
        Index("ix_square_kol_platform_name", "platform", "name"),
    )


class SquareHotTokenSnapshot(TimestampMixin, Base):
    __tablename__ = "square_hot_token_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_key: Mapped[str] = mapped_column(String(120), index=True)
    snapshot_date: Mapped[str] = mapped_column(String(20), index=True)
    window_hours: Mapped[int] = mapped_column(Integer, default=24, index=True)
    platform_scope: Mapped[str] = mapped_column(String(80), index=True)
    kol_only: Mapped[int] = mapped_column(Integer, default=0, index=True)
    rank: Mapped[int] = mapped_column(Integer, index=True)
    token: Mapped[str] = mapped_column(String(20), index=True)
    unique_author_mentions: Mapped[int] = mapped_column(Integer, default=0)
    unique_kol_mentions: Mapped[int] = mapped_column(Integer, default=0)
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    platforms_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    sample_authors_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    latest_published_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_square_snapshot_key_rank", "snapshot_key", "rank"),
        Index("ix_square_snapshot_date_scope", "snapshot_date", "platform_scope", "kol_only"),
    )


class SquareCollectionState(TimestampMixin, Base):
    __tablename__ = "square_collection_states"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(20), index=True)
    language: Mapped[str] = mapped_column(String(20), index=True, default="en")
    current_cursor: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    last_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    last_run_started_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    last_run_finished_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    last_created_count: Mapped[int] = mapped_column(Integer, default=0)
    last_skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    last_page_count: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        Index("ux_square_collection_state_scope", "platform", "language", unique=True),
    )


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
    external_id: Mapped[Optional[str]] = mapped_column(String(160), unique=True, index=True, nullable=True)
    event_id: Mapped[Optional[int]] = mapped_column(BigInteger, index=True, nullable=True)
    address: Mapped[str] = mapped_column(String(100))
    blockchain: Mapped[Optional[str]] = mapped_column(String(30), index=True, nullable=True)
    entity_name: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    label: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    action: Mapped[str] = mapped_column(String(20))
    amount: Mapped[float] = mapped_column(Float)
    amount_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    token: Mapped[str] = mapped_column(String(40))
    tx_hash: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    counterparty_address: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    severity: Mapped[Optional[str]] = mapped_column(String(20), index=True, nullable=True)
    notification_status: Mapped[Optional[str]] = mapped_column(String(20), index=True, nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)


class WhaleNotificationChannel(TimestampMixin, Base):
    __tablename__ = "whale_notification_channels"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    channel_type: Mapped[str] = mapped_column(String(20), index=True)
    target: Mapped[str] = mapped_column(Text)
    min_severity: Mapped[str] = mapped_column(String(20), default="medium")
    is_active: Mapped[int] = mapped_column(Integer, default=1, index=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)


class WhaleNotificationDelivery(TimestampMixin, Base):
    __tablename__ = "whale_notification_deliveries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    alert_id: Mapped[int] = mapped_column(BigInteger, index=True)
    channel_id: Mapped[int] = mapped_column(BigInteger, index=True)
    delivery_status: Mapped[str] = mapped_column(String(20), index=True)
    response_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payload_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)


class WhaleTransferEvent(TimestampMixin, Base):
    __tablename__ = "whale_transfer_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    external_id: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    address: Mapped[str] = mapped_column(String(120), index=True)
    blockchain: Mapped[str] = mapped_column(String(30), index=True, default="ethereum")
    entity_name: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    label: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    direction: Mapped[Optional[str]] = mapped_column(String(20), index=True, nullable=True)
    counterparty_address: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    token: Mapped[Optional[str]] = mapped_column(String(40), index=True, nullable=True)
    amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    amount_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tx_hash: Mapped[Optional[str]] = mapped_column(String(120), index=True, nullable=True)
    occurred_at: Mapped[Optional[str]] = mapped_column(String(50), index=True, nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_whale_transfer_chain_time", "blockchain", "created_at"),
        Index("ix_whale_transfer_address_time", "address", "created_at"),
    )


class WhaleMonitorState(TimestampMixin, Base):
    __tablename__ = "whale_monitor_states"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    scope_key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    last_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    last_run_started_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    last_run_finished_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    watched_address_count: Mapped[int] = mapped_column(Integer, default=0)
    fetched_transfer_count: Mapped[int] = mapped_column(Integer, default=0)
    stored_event_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)


class MonitoredAddress(TimestampMixin, Base):
    __tablename__ = "monitored_addresses"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    address: Mapped[str] = mapped_column(String(120), index=True)
    blockchain: Mapped[str] = mapped_column(String(30), index=True, default="ethereum")
    label: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    entity_name: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    address_type: Mapped[Optional[str]] = mapped_column(String(40), index=True, nullable=True)
    is_whale: Mapped[int] = mapped_column(Integer, default=0, index=True)
    alert_threshold: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    is_active: Mapped[int] = mapped_column(Integer, default=1, index=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        Index("ux_monitored_address_chain", "address", "blockchain", unique=True),
        Index("ix_monitored_type_chain_active", "address_type", "blockchain", "is_active"),
    )


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
