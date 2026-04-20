from __future__ import annotations

import os
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

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    ai_model: str = "gpt-4o-mini"

    binance_square_feed_url: str = ""
    binance_square_openapi_key: str = ""
    okx_public_feed_urls: str = ""
    square_default_language: str = "en"
    square_hot_token_window_hours: int = 24
    square_collect_interval_minutes: int = 10
    square_collect_page_size: int = 40
    square_collect_backfill_pages: int = 3

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
