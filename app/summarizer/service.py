"""Summarization service - Map-Reduce orchestration.

Pipeline:
1. Query raw articles from DB (status='raw')
2. For each article:
   a. If short enough → summarize directly
   b. If long → chunk → parallel map (summarize each chunk) → reduce (synthesize)
3. After all articles are summarized → generate daily digest
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

from app.config import settings
from app.database import (
    get_db,
    get_raw_articles,
    get_raw_articles_for_source,
    update_article_status,
    update_article_summary,
    get_articles_for_date,
    get_digest_for_date,
    insert_daily_digest,
    link_articles_to_digest,
)
from app.summarizer.chunker import chunk_article
from app.summarizer.llm import call_llm, get_last_provider
from app.prompts.manager import prompt_manager

logger = logging.getLogger(__name__)

# How many articles to process in one summarization run
BATCH_SIZE = 50

# How many parallel chunk-summarization calls per article
MAX_CHUNK_WORKERS = 5

# How many articles to summarize in parallel
MAX_ARTICLE_WORKERS = 3


def run_summarization(
    source_id: int | None = None,
    regenerate_dates: list[str] | None = None,
    on_progress=None,
) -> dict:
    """Summarize all raw articles, then regenerate digests for affected dates.

    Args:
        source_id: If provided, only summarize articles from this source.
        regenerate_dates: If provided, only regenerate digests for these dates.
                          If None, auto-detects dates from newly summarized articles.
        on_progress: Optional callback(status_message) for live progress tracking.
    """
    conn = get_db()
    stats = {"articles_processed": 0, "articles_failed": 0, "digest_generated": False}
    affected_dates: set[str] = set(regenerate_dates or [])

    try:
        # 1. Summarize all raw articles, tracking which dates were affected
        if source_id is not None:
            raw_articles = get_raw_articles_for_source(conn, source_id, limit=BATCH_SIZE)
        else:
            raw_articles = get_raw_articles(conn, limit=BATCH_SIZE)
        logger.info(f"Found {len(raw_articles)} raw articles to summarize")

        if on_progress:
            on_progress(f"Found {len(raw_articles)} raw articles")

        total_articles = len(raw_articles)
        for idx, article in enumerate(raw_articles):
            article_id = article["id"]
            title = article["title"]
            raw_text = article.get("raw_text") or article.get("snippet", "")

            # Track this article's date for digest regeneration
            fetched = article.get("fetched_at")
            if fetched:
                if isinstance(fetched, str):
                    affected_dates.add(fetched[:10])
                else:
                    affected_dates.add(fetched.strftime("%Y-%m-%d"))
            else:
                # Fallback: use today in IST
                affected_dates.add(_today_ist_str())

            if not raw_text or len(raw_text) < 100:
                update_article_status(conn, article_id, "failed", "Insufficient content")
                stats["articles_failed"] += 1
                continue

            try:
                update_article_status(conn, article_id, "summarizing")
                conn.commit()

                if on_progress:
                    short_title = title[:60] + "…" if len(title) > 60 else title
                    on_progress(f"Summarizing ({idx + 1}/{total_articles}): {short_title}")

                logger.info(f"Summarizing article #{article_id}: {title[:80]}")
                summary, chunk_count, provider = _summarize_article(raw_text)

                update_article_summary(conn, article_id, summary, chunk_count, provider)
                stats["articles_processed"] += 1
                logger.info(f"Summarized article #{article_id} ({chunk_count} chunks)")

            except Exception as e:
                logger.error(f"Failed to summarize article #{article_id}: {e}")
                update_article_status(conn, article_id, "failed", str(e))
                stats["articles_failed"] += 1

            conn.commit()

        # 2. Regenerate digests for affected dates
        # Find dates with summarized articles but no digest yet
        orphan_rows = conn.execute("""
            SELECT DISTINCT date(a.fetched_at) as d
            FROM articles a
            WHERE a.status = 'summarized'
              AND NOT EXISTS (
                SELECT 1 FROM daily_digests dg WHERE dg.date = date(a.fetched_at)
              )
        """).fetchall()
        for row in orphan_rows:
            affected_dates.add(row["d"])

        if affected_dates:
            logger.info(f"Regenerating digests for {len(affected_dates)} date(s): {sorted(affected_dates)}")
            if on_progress:
                on_progress(f"Generating digests for {len(affected_dates)} date(s)...")
            for date_str in sorted(affected_dates):
                try:
                    _generate_daily_digest(conn, date_str)
                    conn.commit()
                    stats["digest_generated"] = True
                    logger.info(f"Digest generated for {date_str}")
                    if on_progress:
                        on_progress(f"✓ Digest for {date_str}")
                except Exception as e:
                    logger.error(f"Failed to generate digest for {date_str}: {e}")

        return stats

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Article-level Map-Reduce
# ---------------------------------------------------------------------------


def _summarize_article(raw_text: str) -> tuple[str, int, str]:
    """Summarize a single article using map-reduce if it's long.

    Returns (summary_text, chunk_count, provider_used).
    """
    # Truncate overly long articles
    if len(raw_text) > settings.max_article_chars:
        raw_text = raw_text[: settings.max_article_chars]

    # If short enough, summarize directly
    if len(raw_text) <= settings.chunk_size:
        summary = call_llm(prompt_manager.get_prompt("single_summary").format(text=raw_text))
        return summary, 1, get_last_provider()

    # Map-Reduce: chunk → parallel summarize → synthesize
    chunks = chunk_article(raw_text)
    if not chunks:
        return "", 0, ""

    if len(chunks) == 1:
        summary = call_llm(prompt_manager.get_prompt("single_summary").format(text=chunks[0]))
        return summary, 1, get_last_provider()

    # MAP phase: summarize each chunk in parallel
    sub_summaries: list[str] = []
    with ThreadPoolExecutor(max_workers=MAX_CHUNK_WORKERS) as executor:
        futures = {
            executor.submit(call_llm, prompt_manager.get_prompt("chunk_summary").format(text=c)): i
            for i, c in enumerate(chunks)
        }
        for future in as_completed(futures):
            try:
                sub_summaries.append(future.result())
            except Exception as e:
                logger.error(f"Chunk summarization failed: {e}")
                # Don't lose the entire article for one failed chunk
                sub_summaries.append("[chunk failed to summarize]")

    if not sub_summaries:
        return "", 0, ""

    # REDUCE phase: synthesize sub-summaries into one cohesive summary
    combined = "\n\n---\n\n".join(sub_summaries)
    final_summary = call_llm(prompt_manager.get_prompt("reduce_synthesis").format(sub_summaries=combined))

    return final_summary, len(chunks), get_last_provider()


# ---------------------------------------------------------------------------
# Daily Digest Generation
# ---------------------------------------------------------------------------


def _generate_daily_digest(conn, date_str: str, provider: str | None = None, model: str | None = None, on_progress=None) -> None:
    """Generate (or regenerate) the daily digest for a given date."""
    articles = get_articles_for_date(conn, date_str)

    if not articles:
        if on_progress: on_progress("No articles found")
        logger.info(f"No summarized articles for {date_str}, skipping digest")
        return

    if on_progress: on_progress(f"Building prompt from {len(articles)} articles...")

    # Build numbered source list with URLs for citation footnotes & hyperlinks
    source_list_lines = []
    ref_urls = {}  # ref_number -> url
    for i, a in enumerate(articles, start=1):
        source_name = a.get('source_name', 'Unknown')
        title = a['title']
        url = a.get('url', '#')
        source_list_lines.append(f"[{i}] [{source_name} — {title}]({url})")
        ref_urls[i] = url

    # Build article summaries with reference numbers
    article_summaries = "\n\n---\n\n".join(
        f"[REF {i}] SOURCE: {a.get('source_name', 'Unknown')} | {a.get('source_category', '')}\n"
        f"TITLE: {a['title']}\n"
        f"SUMMARY: {a['summary_text']}"
        for i, a in enumerate(articles, start=1)
    )

    source_footnote = "\n".join(source_list_lines)

    if on_progress: on_progress("Sending to LLM...")

    digest_text = call_llm(
        prompt_manager.get_prompt("daily_digest").format(
            date=date_str,
            article_summaries=article_summaries,
        ),
        provider=provider,
        model=model,
        max_tokens=8192,
        on_progress=on_progress,
    )

    # Convert in-text [N] and [N][M] tags to clickable markdown links
    import re
    def _make_links(m):
        nums = re.findall(r'\d+', m.group(0))
        parts = []
        for n_str in nums:
            n = int(n_str)
            url = ref_urls.get(n, '#')
            parts.append(f"[[{n}]]({url})")
        return ''.join(parts)
    digest_text = re.sub(r'(?:\[\d+\])+', _make_links, digest_text)

    # Append source footnote with clickable links
    digest_text += f"\n\n## 📚 Sources\n\n{source_footnote}"

    if on_progress: on_progress("LLM responded, saving...")

    # Count unique sources
    unique_sources = len({a.get("source_id") for a in articles})

    # Generate title
    title = f"Daily Digest - {_format_date_pretty(date_str)}"

    digest_id = insert_daily_digest(
        conn,
        date_str=date_str,
        title=title,
        summary_text=digest_text,
        article_count=len(articles),
        source_count=unique_sources,
    )

    # Link articles to digest
    article_ids = [a["id"] for a in articles]
    link_articles_to_digest(conn, digest_id, article_ids)

    logger.info(
        f"Daily digest generated for {date_str}: "
        f"{len(articles)} articles from {unique_sources} sources"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _today_ist_str() -> str:
    """Return today's date in IST as ISO string (YYYY-MM-DD)."""
    ist = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(ist).strftime("%Y-%m-%d")


def _format_date_pretty(date_str: str) -> str:
    """Convert ISO date to a pretty format, e.g. '29 May 2026'."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%d %B %Y")
    except ValueError:
        return date_str
