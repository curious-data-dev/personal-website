"""Summarization service — Map-Reduce orchestration.

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
    update_article_status,
    update_article_summary,
    get_articles_for_date,
    get_digest_for_date,
    insert_daily_digest,
    link_articles_to_digest,
)
from app.summarizer.chunker import chunk_article
from app.summarizer.llm import call_llm

logger = logging.getLogger(__name__)

# How many articles to process in one summarization run
BATCH_SIZE = 50

# How many parallel chunk-summarization calls per article
MAX_CHUNK_WORKERS = 5

# How many articles to summarize in parallel
MAX_ARTICLE_WORKERS = 3


def run_summarization(regenerate_dates: list[str] | None = None) -> dict:
    """Summarize all raw articles, then regenerate digests for affected dates.

    Args:
        regenerate_dates: If provided, only regenerate digests for these dates.
                          If None, auto-detects dates from newly summarized articles.
    """
    conn = get_db()
    stats = {"articles_processed": 0, "articles_failed": 0, "digest_generated": False}
    affected_dates: set[str] = set(regenerate_dates or [])

    try:
        # 1. Summarize all raw articles, tracking which dates were affected
        raw_articles = get_raw_articles(conn, limit=BATCH_SIZE)
        logger.info(f"Found {len(raw_articles)} raw articles to summarize")

        for article in raw_articles:
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

            if not raw_text or len(raw_text) < 100:
                update_article_status(conn, article_id, "failed", "Insufficient content")
                stats["articles_failed"] += 1
                continue

            try:
                update_article_status(conn, article_id, "summarizing")
                conn.commit()

                logger.info(f"Summarizing article #{article_id}: {title[:80]}")
                summary, chunk_count = _summarize_article(raw_text)

                update_article_summary(conn, article_id, summary, chunk_count)
                stats["articles_processed"] += 1
                logger.info(f"Summarized article #{article_id} ({chunk_count} chunks)")

            except Exception as e:
                logger.error(f"Failed to summarize article #{article_id}: {e}")
                update_article_status(conn, article_id, "failed", str(e))
                stats["articles_failed"] += 1

            conn.commit()

        # 2. Regenerate digests ONLY for dates with newly summarized articles
        if stats["articles_processed"] > 0:
            logger.info(f"Regenerating digests for {len(affected_dates)} date(s): {sorted(affected_dates)}")
            for date_str in sorted(affected_dates):
                try:
                    _generate_daily_digest(conn, date_str)
                    conn.commit()
                    stats["digest_generated"] = True
                    logger.info(f"Digest generated for {date_str}")
                except Exception as e:
                    logger.error(f"Failed to generate digest for {date_str}: {e}")

        return stats

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Article-level Map-Reduce
# ---------------------------------------------------------------------------


def _summarize_article(raw_text: str) -> tuple[str, int]:
    """Summarize a single article using map-reduce if it's long.

    Returns (summary_text, chunk_count).
    """
    # Truncate overly long articles
    if len(raw_text) > settings.max_article_chars:
        raw_text = raw_text[: settings.max_article_chars]

    # If short enough, summarize directly
    if len(raw_text) <= settings.chunk_size:
        summary = call_llm(_SINGLE_SUMMARY_PROMPT.format(text=raw_text))
        return summary, 1

    # Map-Reduce: chunk → parallel summarize → synthesize
    chunks = chunk_article(raw_text)
    if not chunks:
        return "", 0

    if len(chunks) == 1:
        summary = call_llm(_SINGLE_SUMMARY_PROMPT.format(text=chunks[0]))
        return summary, 1

    # MAP phase: summarize each chunk in parallel
    sub_summaries: list[str] = []
    with ThreadPoolExecutor(max_workers=MAX_CHUNK_WORKERS) as executor:
        futures = {
            executor.submit(call_llm, _CHUNK_SUMMARY_PROMPT.format(text=c)): i
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
        return "", 0

    # REDUCE phase: synthesize sub-summaries into one cohesive summary
    combined = "\n\n---\n\n".join(sub_summaries)
    final_summary = call_llm(_REDUCE_PROMPT.format(sub_summaries=combined))

    return final_summary, len(chunks)


# ---------------------------------------------------------------------------
# Daily Digest Generation
# ---------------------------------------------------------------------------


def _generate_daily_digest(conn, date_str: str) -> None:
    """Generate (or regenerate) the daily digest for a given date."""
    articles = get_articles_for_date(conn, date_str)

    if not articles:
        logger.info(f"No summarized articles for {date_str}, skipping digest")
        return

    # Build a digest from article summaries
    article_summaries = "\n\n---\n\n".join(
        f"SOURCE: {a.get('source_name', 'Unknown')} | {a.get('source_category', '')}\n"
        f"TITLE: {a['title']}\n"
        f"SUMMARY: {a['summary_text']}"
        for a in articles
    )

    digest_text = call_llm(
        _DIGEST_PROMPT.format(date=date_str, article_summaries=article_summaries)
    )

    # Count unique sources
    unique_sources = len({a.get("source_id") for a in articles})

    # Generate title
    title = f"Daily Digest — {_format_date_pretty(date_str)}"

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
# Prompt Templates
# ---------------------------------------------------------------------------

_SINGLE_SUMMARY_PROMPT = """You are a skilled news summarizer. Summarize the following article concisely.

Guidelines:
- 3-5 paragraphs maximum
- Preserve all key facts, names, numbers, and dates
- Neutral, objective tone — no editorialising
- Write in clear, simple English
- Do NOT include phrases like "This article discusses" or "The author states"

ARTICLE:
{text}

SUMMARY:"""

_CHUNK_SUMMARY_PROMPT = """Summarize this excerpt from a longer article. Focus on:
- Key facts and events mentioned
- Important names, numbers, and dates
- The main argument or development

Write 2-3 concise paragraphs. Do not editorialise.

EXCERPT:
{text}

SUMMARY:"""

_REDUCE_PROMPT = """You are a news editor. Below are summaries of different sections of the same article.
Synthesize them into ONE cohesive summary.

Guidelines:
- Remove any redundancy or repetition across sections
- Preserve ALL key facts, names, numbers, and dates
- 4-6 paragraphs in chronological/logical order
- Neutral, objective tone
- Do NOT mention that these were sub-summaries

SUB-SUMMARIES:
{sub_summaries}

SYNTHESIZED SUMMARY:"""

_DIGEST_PROMPT = """You are a daily news editor. Synthesize the following article summaries into one cohesive daily digest for {date}.

Guidelines:
- Group related stories under section headings (e.g., "📰 Politics & Policy", "📈 Markets & Economy", "🌍 World News")
- 2-3 paragraphs per section
- Start with a 1-2 sentence "Today's Highlights" overview
- Preserve key facts, numbers, and names
- Neutral, objective tone
- End with a "💡 Key Takeaway" summary bullet list (3-5 points)

ARTICLE SUMMARIES:
{article_summaries}

DAILY DIGEST:"""


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
