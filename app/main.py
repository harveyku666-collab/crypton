"""FastAPI application entry point with lifespan management."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("bitinfo")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.address_intel.legacy_store import close_legacy_engines
    from app.common.database import init_db, close_db
    from app.common.http_client import close_client, get_proxy_status
    from app.common.cache import close_redis
    from app.common.scheduler import start_scheduler, stop_scheduler
    from app.market.jobs import register_market_jobs
    from app.news.jobs import register_news_jobs
    from app.analysis.jobs import register_analysis_jobs
    from app.briefing.jobs import register_briefing_jobs
    from app.square.jobs import register_square_jobs
    from app.onchain.jobs import register_onchain_jobs
    from app.address_intel.jobs import register_address_intel_jobs

    logger.info("Starting %s v%s", settings.project_name, settings.version)
    proxy_status = get_proxy_status()
    if proxy_status["configured"]:
        logger.info("Outbound proxy enabled for restricted hosts: %s", proxy_status["url"])
    else:
        logger.warning(
            "Outbound proxy is not configured. Restricted hosts may fail: %s",
            ", ".join(proxy_status["restricted_hosts"]),
        )

    try:
        await init_db()
    except Exception:
        logger.warning("DB init skipped (not available)")

    register_market_jobs()
    register_news_jobs()
    register_analysis_jobs()
    register_briefing_jobs()
    register_square_jobs()
    register_onchain_jobs()
    register_address_intel_jobs()
    start_scheduler()

    yield

    stop_scheduler()
    await close_client()
    await close_redis()
    await close_legacy_engines()
    await close_db()
    logger.info("Shutdown complete")


app = FastAPI(
    title=settings.project_name,
    version=settings.version,
    debug=settings.debug,
    lifespan=lifespan,
)

from pathlib import Path  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from app.api.v1.router import api_router  # noqa: E402

app.include_router(api_router)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/health")
async def health():
    from app.common.http_client import get_proxy_status

    proxy_status = get_proxy_status()
    return {
        "status": "ok",
        "version": settings.version,
        "proxy_configured": proxy_status["configured"],
    }


@app.get("/")
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/skill")
async def skill_detail_page():
    return FileResponse(str(STATIC_DIR / "skill.html"))


@app.get("/daily")
async def daily_report_page():
    return FileResponse(str(STATIC_DIR / "daily.html"))


@app.get("/briefing")
async def briefing_page():
    return FileResponse(str(STATIC_DIR / "briefing.html"))


@app.get("/market-rank")
async def market_rank_page():
    return FileResponse(str(STATIC_DIR / "market-rank.html"))


@app.get("/oi-signal")
async def oi_signal_page():
    return FileResponse(str(STATIC_DIR / "oi-signal.html"))


@app.get("/defi-yield-scanner")
async def defi_yield_scanner_page():
    return FileResponse(str(STATIC_DIR / "defi-yield-scanner.html"))


@app.get("/prediction-advanced")
async def prediction_advanced_page():
    return FileResponse(str(STATIC_DIR / "prediction-advanced.html"))


@app.get("/okx-intelligence")
async def okx_intelligence_page():
    return FileResponse(str(STATIC_DIR / "okx-intelligence.html"))


@app.get("/market-intel")
async def market_intel_page():
    return FileResponse(str(STATIC_DIR / "market-intel.html"))


@app.get("/square")
async def square_page():
    return FileResponse(str(STATIC_DIR / "square.html"))


@app.get("/address-intel")
async def address_intel_page():
    return FileResponse(str(STATIC_DIR / "address-intel.html"))


@app.get("/whale-monitor")
async def whale_monitor_page():
    return FileResponse(str(STATIC_DIR / "whale-monitor.html"))
