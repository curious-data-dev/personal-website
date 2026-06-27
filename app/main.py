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
from app.scraper.youtube.service import run_youtube_scrape
from app.summarizer.service import run_summarization
from app.transcripts import process_pending_transcripts

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
    2. Scrape YouTube channels → fetch transcripts → store
    3. Summarize all raw articles → store summaries
    4. Generate RSS daily digest + YouTube daily digest
    """
    logger.info("=" * 60)
    logger.info("DAILY JOB STARTED — Scrape + Summarize")
    logger.info("=" * 60)

    total_new = 0

    try:
        # Phase 1: RSS feeds
        logger.info("▶ Phase 1/3: Scraping RSS feeds...")
        scrape_stats = run_scrape()
        logger.info(f"RSS scrape done: {scrape_stats}")
        total_new += scrape_stats.get("articles_new", 0)

        # Phase 2: YouTube channels — discover videos, defer transcripts
        logger.info("▶ Phase 2/4: Scraping YouTube channels...")
        yt_stats = run_youtube_scrape(defer_transcripts=True)
        logger.info(f"YouTube scrape done: {yt_stats}")
        total_new += yt_stats.get("videos_new", 0)

        # Phase 3: Process transcripts through provider chain
        #         (direct → supadata → ...). On local: direct works.
        #         On VPS: direct blocked → falls back to supadata.
        logger.info("▶ Phase 3/4: Processing transcripts...")
        transcript_stats = process_pending_transcripts()
        logger.info(f"Transcript processing done: {transcript_stats}")
        total_new += transcript_stats.get("completed", 0)

        # Phase 4: Summarization
        if total_new > 0:
            logger.info(f"▶ Phase 4/4: Summarizing new items + generating digests...")
            summary_stats = run_summarization()
            logger.info(f"Summarization & digests done: {summary_stats}")
        else:
            logger.info("No new content — skipping summarization")

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
