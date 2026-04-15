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
    from app.common.database import init_db, close_db
    from app.common.http_client import close_client
    from app.common.cache import close_redis
    from app.common.scheduler import start_scheduler, stop_scheduler
    from app.market.jobs import register_market_jobs
    from app.news.jobs import register_news_jobs
    from app.analysis.jobs import register_analysis_jobs
    from app.briefing.jobs import register_briefing_jobs

    logger.info("Starting %s v%s", settings.project_name, settings.version)

    try:
        await init_db()
    except Exception:
        logger.warning("DB init skipped (not available)")

    register_market_jobs()
    register_news_jobs()
    register_analysis_jobs()
    register_briefing_jobs()
    start_scheduler()

    yield

    stop_scheduler()
    await close_client()
    await close_redis()
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
    return {"status": "ok", "version": settings.version}


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
