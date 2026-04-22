from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    project_name: str = "BitInfo Trading Platform"
    version: str = "0.1.0"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://bitinfo:bitinfo@localhost:5432/bitinfo"
    redis_url: str = "redis://localhost:6379/0"
    proxy_url: str = ""

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    ai_model: str = "gpt-4o-mini"

    binance_square_feed_url: str = ""
    binance_square_openapi_key: str = ""
    okx_public_feed_urls: str = ""
    square_default_language: str = "en"
    square_hot_token_window_hours: int = 24
    square_hot_token_min_unique_authors: int = 2
    square_hot_token_min_unique_kol_mentions: int = 2
    square_collect_interval_minutes: int = 10
    square_collect_page_size: int = 40
    square_collect_backfill_pages: int = 3
    address_intel_registry_database_url: str = ""
    address_intel_activity_database_url: str = ""
    address_intel_sync_hour: int = 7
    address_intel_sync_minute: int = 15
    address_intel_legacy_sync_limit: int = 1000
    onchain_whale_monitor_interval_minutes: int = 15
    onchain_whale_transfer_limit: int = 20
    onchain_whale_min_usd: float = 1000000.0
    onchain_whale_max_addresses: int = 25
    onchain_whale_notify_timeout_seconds: int = 10

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
