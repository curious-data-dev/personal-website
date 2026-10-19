"""FastAPI application entry point.

Single process that runs:
- Web server (uvicorn)
- Background scheduler (APScheduler)
- All in one container, one process
"""

import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import init_db
from app.orchestration import enqueue_scheduled_run
from app.web.routes import router as web_router

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
    """Enqueue the daily pipeline for the worker to execute.

    The app process only serves web traffic and schedules the job. Keeping the
    heavy pipeline in the worker gives a single writer (no app/worker race) and
    lets a run survive app restarts. The worker runs scrape → transcripts →
    summarization/digests → Kindle.
    """
    logger.info("=" * 60)
    logger.info("DAILY JOB — enqueueing scheduled run")
    logger.info("=" * 60)
    try:
        run_id = enqueue_scheduled_run()
        logger.info(f"Enqueued scheduled run #{run_id}; worker will execute it.")
    except Exception:
        logger.exception("Failed to enqueue scheduled run")
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
