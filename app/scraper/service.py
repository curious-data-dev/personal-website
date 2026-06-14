"""Scraper service — fetches RSS feeds, extracts articles, stores in DB."""

import logging
from datetime import datetime, timezone

from app.database import (
    get_db,
    get_active_sources,
    insert_article,
    article_exists,
    update_source_last_fetched,
    start_scrape_log,
    finish_scrape_log,
)
from app.scraper.feed_reader import fetch_feed_entries
from app.scraper.article_extractor import extract_article_text

logger = logging.getLogger(__name__)


def run_scrape(
    start_date: str | None = None,
    end_date: str | None = None,
    source_ids: list[int] | None = None,
    on_progress=None,
) -> dict:
    """Main entry point. Called by scheduler or manual trigger.

    Args:
        start_date: ISO date string (YYYY-MM-DD) — only include articles from this date onward.
        end_date: ISO date string (YYYY-MM-DD) — only include articles up to this date.
        source_ids: If provided, only scrape these specific sources. If None, all active.
        on_progress: Optional callback(status_message) for live progress tracking.

    Returns a summary dict with scrape statistics.
    """
    conn = get_db()
    stats = {
        "feeds_total": 0,
        "feeds_success": 0,
        "feeds_failed": 0,
        "articles_new": 0,
        "articles_skipped": 0,
        "errors": [],
    }

    # Parse date range
    since: datetime | None = None
    until: datetime | None = None
    if start_date:
        try:
            since = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            logger.warning(f"Invalid start_date: {start_date}, ignoring")
    if end_date:
        try:
            until = datetime.strptime(end_date, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59, tzinfo=timezone.utc
            )
        except ValueError:
            logger.warning(f"Invalid end_date: {end_date}, ignoring")

    log_id = start_scrape_log(conn)

    try:
        # 1. Fetch sources from DB
        if source_ids:
            # Fetch specific sources by ID (for per-feed testing)
            placeholders = ",".join("?" * len(source_ids))
            rows = conn.execute(
                f"SELECT * FROM sources WHERE id IN ({placeholders}) ORDER BY category, name",
                source_ids,
            ).fetchall()
            sources = [dict(r) for r in rows]
        else:
            sources = get_active_sources(conn)
        stats["feeds_total"] = len(sources)

        # 2. For each source, fetch entries and extract article text
        total = len(sources)
        for idx, source in enumerate(sources):
            feed_url = source["feed_url"]
            source_id = source["id"]
            source_name = source["name"]

            if on_progress:
                on_progress(f"Fetching {source_name} ({idx + 1}/{total})")

            try:
                logger.info(f"Fetching feed: {source_name} ({feed_url})")
                entries = fetch_feed_entries(feed_url, since=since, until=until)

                for entry in entries:
                    url = entry["url"]
                    if not url:
                        continue

                    if article_exists(conn, url):
                        stats["articles_skipped"] += 1
                        continue

                    # Extract full article text
                    logger.debug(f"Extracting article: {entry['title'][:80]}")
                    raw_text = extract_article_text(url)

                    article_id = insert_article(
                        conn,
                        source_id=source_id,
                        url=url,
                        title=entry["title"],
                        snippet=entry.get("snippet", ""),
                        raw_text=raw_text or entry.get("snippet", ""),
                        author=entry.get("author", ""),
                        published_at=entry.get("published"),
                        # When using custom date range, use the article's real publish date
                        fetched_at=entry.get("published") if (start_date or end_date) else None,
                        status="raw",
                    )

                    if article_id:
                        stats["articles_new"] += 1
                        logger.debug(f"Stored article #{article_id}: {entry['title'][:80]}")

                update_source_last_fetched(conn, source_id)
                stats["feeds_success"] += 1
                if on_progress:
                    on_progress(f"✓ {source_name}: {stats['articles_new']} new articles")

            except Exception as e:
                logger.error(f"Failed to process feed '{source_name}': {e}")
                stats["feeds_failed"] += 1
                if on_progress:
                    on_progress(f"✗ {source_name}: failed")
                stats["errors"].append({
                    "feed": source_name,
                    "url": feed_url,
                    "error": str(e),
                })

            conn.commit()

        # 3. Finalise scrape log
        finish_scrape_log(conn, log_id, **stats)
        conn.commit()

        logger.info(
            f"Scrape complete: {stats['feeds_success']}/{stats['feeds_total']} feeds, "
            f"{stats['articles_new']} new articles, {stats['articles_skipped']} skipped"
        )

    except Exception as e:
        logger.exception("Scrape failed with unhandled error")
        raise
    finally:
        conn.close()

    return stats
