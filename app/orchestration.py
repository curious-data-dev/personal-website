"""One durable end-to-end RSS and YouTube run."""

import logging

from app.database import get_db, update_run
from app.scraper.service import run_scrape
from app.scraper.youtube.service import run_youtube_scrape
from app.summarizer.service import run_summarization
from app.transcripts import process_pending_transcripts

logger = logging.getLogger(__name__)


def execute_run(run: dict) -> None:
    run_id = run["id"]
    conn = get_db()
    errors: list[dict] = []
    counters: dict = {}
    try:
        sources = conn.execute("SELECT * FROM run_sources WHERE run_id=?", (run_id,)).fetchall()
        rss_ids = [r["source_id"] for r in sources if r["source_type"] == "rss"]
        youtube_ids = [r["source_id"] for r in sources if r["source_type"] == "youtube"]
    finally:
        conn.close()

    try:
        if rss_ids:
            stage_conn = get_db(); update_run(stage_conn, run_id, stage="fetching_rss"); stage_conn.close()
            result = run_scrape(run["start_date"], run["end_date"], rss_ids, run_id=run_id)
            counters["rss"] = result
            errors.extend({"branch": "rss", **e} for e in result.get("errors", []))
        if youtube_ids:
            conn2 = get_db(); update_run(conn2, run_id, stage="discovering_youtube"); conn2.close()
            result = run_youtube_scrape(
                source_ids=youtube_ids, start_date=run["start_date"], end_date=run["end_date"],
                run_id=run_id, defer_transcripts=True,
            )
            counters["youtube"] = result
            errors.extend({"branch": "youtube", **e} for e in result.get("errors", []))
            conn2 = get_db(); update_run(conn2, run_id, stage="retrieving_transcripts"); conn2.close()
            counters["transcripts"] = process_pending_transcripts(run_id)
            transcript_failures = {
                key: counters["transcripts"].get(key, 0)
                for key in ("retry", "failed", "unavailable")
                if counters["transcripts"].get(key, 0)
            }
            if transcript_failures:
                errors.append({
                    "branch": "transcripts",
                    "error": "Transcript processing incomplete",
                    "counts": transcript_failures,
                })

        conn2 = get_db(); update_run(conn2, run_id, stage="summarizing", counters=counters, errors=errors); conn2.close()
        selected_types = ({"rss"} if rss_ids else set()) | ({"youtube"} if youtube_ids else set())
        summary = run_summarization(source_types=selected_types)
        counters["summaries"] = summary

        conn2 = get_db()
        affected = conn2.execute(
            """SELECT DISTINCT s.source_type, a.published_date_ist AS digest_date
               FROM run_items ri JOIN articles a ON a.id=ri.article_id
               JOIN sources s ON s.id=a.source_id
               WHERE ri.run_id=? AND a.status='summarized' AND a.published_date_ist IS NOT NULL""",
            (run_id,),
        ).fetchall()
        for row in affected:
            table = "daily_digests" if row["source_type"] == "rss" else "youtube_digests"
            digest = conn2.execute(f"SELECT id FROM {table} WHERE date=?", (row["digest_date"],)).fetchone()
            conn2.execute(
                """INSERT INTO run_affected_dates(run_id, source_type, digest_date, status, digest_id)
                   VALUES (?, ?, ?, 'completed', ?) ON CONFLICT(run_id, source_type, digest_date)
                   DO UPDATE SET status='completed', digest_id=excluded.digest_id""",
                (run_id, row["source_type"], row["digest_date"], digest["id"] if digest else None),
            )
        new_count = counters.get("rss", {}).get("articles_new", 0) + counters.get("youtube", {}).get("videos_new", 0)
        final_status = "partial" if errors else ("no_new_content" if new_count == 0 and summary.get("articles_processed", 0) == 0 else "completed")
        update_run(conn2, run_id, stage="complete", status=final_status, counters=counters, errors=errors)
        conn2.close()
    except Exception as exc:
        logger.exception("Run %s failed", run_id)
        errors.append({"branch": "orchestration", "error": str(exc)})
        conn2 = get_db(); update_run(conn2, run_id, stage="failed", status="failed", counters=counters, errors=errors); conn2.close()
