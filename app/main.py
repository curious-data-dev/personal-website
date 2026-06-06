"""FastAPI application entry point.

Single process that runs:
- Web server (uvicorn)
- Background scheduler (APScheduler)
- All in one container, one process
"""

import logging
from contextlib import asynccontextmanager
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import init_db
from app.web.routes import router as web_router
from app.scraper.service import run_scrape
from app.summarizer.service import run_summarization

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

scheduler = BackgroundScheduler(timezone="Asia/Kolkata")


@scheduler.scheduled_job(
    "cron",
    hour=settings.scrape_cron_hour,
    minute=settings.scrape_cron_minute,
    id="daily_scrape_and_summarize",
)
def daily_scrape_and_summarize() -> None:
    """Run daily at configured time (default 8:00 PM IST).

    1. Scrape all RSS feeds → store raw articles in SQLite
    2. Summarize all raw articles → store summaries
    3. Generate daily digest
    """
    logger.info("=" * 60)
    logger.info("DAILY JOB STARTED — Scrape + Summarize")
    logger.info("=" * 60)

    try:
        logger.info("▶ Phase 1/2: Scraping feeds...")
        scrape_stats = run_scrape()
        logger.info(f"Scrape done: {scrape_stats}")

        if scrape_stats.get("articles_new", 0) > 0:
            logger.info("▶ Phase 2/2: Summarizing new articles...")
            summary_stats = run_summarization()
            logger.info(f"Summarization done: {summary_stats}")
        else:
            logger.info("No new articles — skipping summarization")

    except Exception as e:
        logger.exception("Daily job failed!")

    logger.info("DAILY JOB COMPLETE")
    logger.info("=" * 60)


# ---------------------------------------------------------------------------
# App Lifecycle
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    # Startup
    logger.info("Initializing database...")
    init_db()
    logger.info("Database ready.")

    scheduler.start()
    logger.info(
        f"Scheduler started. Daily scrape at "
        f"{settings.scrape_cron_hour:02d}:{settings.scrape_cron_minute:02d} IST."
    )

    # Optional: log next run time
    job = scheduler.get_job("daily_scrape_and_summarize")
    if job and job.next_run_time:
        logger.info(f"Next scheduled run: {job.next_run_time}")

    yield

    # Shutdown
    logger.info("Shutting down scheduler...")
    scheduler.shutdown()
    logger.info("Goodbye.")


# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="RSS Digest",
    description="Personal news aggregation and summarization engine",
    version="2.0.0",
    lifespan=lifespan,
)

# Static files (CSS)
app.mount("/static", StaticFiles(directory="app/web/static"), name="static")

# Web routes
app.include_router(web_router)
