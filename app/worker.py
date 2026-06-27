"""Single-concurrency durable orchestration worker."""

import logging
import socket
import time

from app.config import settings
from app.database import claim_next_run, get_db, init_db
from app.orchestration import execute_run
from app.transcripts import process_pending_transcripts, _providers
from app.summarizer.service import run_summarization

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    init_db()
    worker_id = socket.gethostname()
    logger.info("Worker %s started", worker_id)
    configured_providers = [provider.name for provider in _providers()]
    if configured_providers:
        logger.info("Transcript providers enabled: %s", ", ".join(configured_providers))
    else:
        logger.error(
            "No transcript provider is configured. YouTube jobs will retry but cannot complete. "
            "Set a provider API key or use YOUTUBE_TRANSCRIPT_PROVIDERS=direct for local testing."
        )
    while True:
        conn = get_db()
        try:
            run = claim_next_run(conn, worker_id, settings.worker_lease_minutes)
        finally:
            conn.close()
        if run:
            execute_run(run)
        else:
            transcript_stats = process_pending_transcripts()
            if transcript_stats["completed"]:
                run_summarization()
            time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
