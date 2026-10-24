"""Summarization service - article summaries and digest generation.

Pipeline:
1. Query raw articles from DB (status='raw')
2. Summarize each article in a single LLM call (no chunk/reduce; the model's
   context window comfortably covers the truncated article)
3. After all articles are summarized → generate daily digest
"""

import logging
import re
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
    get_youtube_articles_for_date,
    insert_youtube_digest,
    link_videos_to_youtube_digest,
)
from app.summarizer.llm import (
    call_llm,
    get_last_provider,
    is_rate_limit_error,
)
from app.prompts.manager import (
    DIGEST_MERGE,
    RSS_STORY_EXTRACT,
    RSS_SUMMARY,
    YOUTUBE_STORY_EXTRACT,
    YOUTUBE_SUMMARY,
    prompt_manager,
)

logger = logging.getLogger(__name__)

# How many articles to process in one summarization run
BATCH_SIZE = 50

# How many articles to summarize in parallel
MAX_ARTICLE_WORKERS = 3


def run_summarization(
    source_id: int | None = None,
    regenerate_dates: list[str] | None = None,
    source_types: set[str] | None = None,
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
    selected_types = source_types or {"rss", "youtube"}
    stats = {"articles_processed": 0, "articles_failed": 0, "articles_rate_limited": 0, "digest_generated": False, "digest_failed": 0, "digests_regenerated": {"rss": [], "youtube": []}}
    affected_dates = {
        "rss": set(regenerate_dates or []),
        "youtube": set(regenerate_dates or []),
    }

    try:
        # 1. Summarize all raw articles, tracking which dates were affected
        if source_id is not None:
            raw_articles = get_raw_articles_for_source(conn, source_id, limit=BATCH_SIZE)
        else:
            placeholders = ",".join("?" for _ in selected_types)
            rows = conn.execute(
                f"""SELECT a.*, s.source_type FROM articles a
                    JOIN sources s ON s.id=a.source_id
                    WHERE a.status='raw' AND s.source_type IN ({placeholders})
                    ORDER BY a.fetched_at LIMIT ?""",
                (*sorted(selected_types), BATCH_SIZE),
            ).fetchall()
            raw_articles = [dict(row) for row in rows]
        logger.info(f"Found {len(raw_articles)} raw articles to summarize")

        if on_progress:
            on_progress(f"Found {len(raw_articles)} raw articles")

        total_articles = len(raw_articles)
        for idx, article in enumerate(raw_articles):
            article_id = article["id"]
            title = article["title"]
            raw_text = article.get("raw_text") or article.get("snippet", "")

            published_date = article.get("published_date_ist")
            item_source_type = article.get("source_type")
            if not item_source_type:
                item_source_type = conn.execute(
                    "SELECT source_type FROM sources WHERE id=?", (article["source_id"],)
                ).fetchone()["source_type"]

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
                is_youtube = item_source_type == "youtube"
                prompt_name = YOUTUBE_SUMMARY if is_youtube else RSS_SUMMARY
                summary, chunk_count, provider = _summarize_article(raw_text, prompt_name=prompt_name)

                update_article_summary(conn, article_id, summary, chunk_count, provider)
                if published_date:
                    affected_dates[item_source_type].add(published_date)
                stats["articles_processed"] += 1
                logger.info(f"Summarized article #{article_id} ({chunk_count} chunks)")

            except Exception as e:
                if is_rate_limit_error(e):
                    # Transient per-minute token limit — requeue so the next run retries,
                    # instead of permanently marking the article failed.
                    update_article_status(conn, article_id, "raw", f"rate limited: {e}")
                    stats["articles_rate_limited"] += 1
                    logger.warning(
                        f"Article #{article_id} hit rate limit, requeued for next run: {e}"
                    )
                else:
                    logger.error(f"Failed to summarize article #{article_id}: {e}")
                    update_article_status(conn, article_id, "failed", str(e))
                    stats["articles_failed"] += 1

            conn.commit()

        # 2. Regenerate digests for affected dates
        # Find dates with summarized articles but no digest yet
        orphan_rows = conn.execute("""
            SELECT DISTINCT a.published_date_ist as d
            FROM articles a
            JOIN sources s ON s.id = a.source_id
            WHERE a.status = 'summarized' AND s.source_type = 'rss'
              AND NOT EXISTS (
                SELECT 1 FROM daily_digests dg WHERE dg.date = a.published_date_ist
              )
        """).fetchall()
        for row in orphan_rows:
            if row["d"]:
                affected_dates["rss"].add(row["d"])

        # ── Stale digest detection: dates within the stale-digest window that
        # have a digest but some summarized articles are not linked to it ──
        if "rss" in selected_types:
            ist = timezone(timedelta(hours=5, minutes=30))
            today_ist = datetime.now(ist).date()
            window_days = settings.stale_digest_window_days
            window_dates = [
                (today_ist - timedelta(days=i)).isoformat()
                for i in range(window_days)
            ]
            placeholders = ",".join("?" * len(window_dates))
            stale_rows = conn.execute(f"""
                SELECT DISTINCT a.published_date_ist AS d
                FROM articles a
                JOIN sources s ON s.id = a.source_id
                WHERE s.source_type = 'rss'
                  AND a.status = 'summarized'
                  AND a.excluded_at IS NULL
                  AND a.published_date_ist IN ({placeholders})
                  AND EXISTS (
                    SELECT 1 FROM daily_digests dg WHERE dg.date = a.published_date_ist
                  )
                  AND NOT EXISTS (
                    SELECT 1 FROM digest_articles da
                    JOIN daily_digests dg ON dg.id = da.digest_id
                    WHERE da.article_id = a.id AND dg.date = a.published_date_ist
                  )
            """, window_dates).fetchall()
            for row in stale_rows:
                if row["d"]:
                    affected_dates["rss"].add(row["d"])

        if "rss" in selected_types and affected_dates["rss"]:
            logger.info(f"Regenerating RSS digests for {len(affected_dates['rss'])} date(s): {sorted(affected_dates['rss'])}")
            if on_progress:
                on_progress(f"Generating RSS digests for {len(affected_dates['rss'])} date(s)...")
            for date_str in sorted(affected_dates["rss"]):
                try:
                    _generate_daily_digest(conn, date_str)
                    conn.commit()
                    stats["digest_generated"] = True
                    stats["digests_regenerated"]["rss"].append(date_str)
                    logger.info(f"RSS digest generated for {date_str}")
                    if on_progress:
                        on_progress(f"✓ RSS digest for {date_str}")
                except Exception as e:
                    logger.exception(f"Failed to generate RSS digest for {date_str}: {e}")
                    stats["digest_failed"] += 1

        # ── YouTube digests: detect orphan dates with YT videos but no digest ──
        yt_affected_dates = affected_dates["youtube"]
        yt_orphan_rows = conn.execute("""
            SELECT DISTINCT a.published_date_ist as d
            FROM articles a
            JOIN sources s ON a.source_id = s.id
            WHERE s.source_type = 'youtube'
              AND a.status = 'summarized'
              AND NOT EXISTS (
                SELECT 1 FROM youtube_digests yd WHERE yd.date = a.published_date_ist
              )
        """).fetchall()
        for row in yt_orphan_rows:
            if row["d"]:
                yt_affected_dates.add(row["d"])

        if "youtube" in selected_types and yt_affected_dates:
            logger.info(f"Regenerating YouTube digests for {len(yt_affected_dates)} date(s): {sorted(yt_affected_dates)}")
            if on_progress:
                on_progress(f"Generating YouTube digests for {len(yt_affected_dates)} date(s)...")
            for date_str in sorted(yt_affected_dates):
                try:
                    _generate_youtube_daily_digest(conn, date_str)
                    conn.commit()
                    stats["digest_generated"] = True
                    stats["digests_regenerated"]["youtube"].append(date_str)
                    logger.info(f"YouTube digest generated for {date_str}")
                    if on_progress:
                        on_progress(f"✓ YouTube digest for {date_str}")
                except Exception as e:
                    logger.exception(f"Failed to generate YouTube digest for {date_str}: {e}")
                    stats["digest_failed"] += 1

        return stats

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Article-level Map-Reduce
# ---------------------------------------------------------------------------


def _summarize_article(raw_text: str, prompt_name: str = RSS_SUMMARY) -> tuple[str, int, str]:
    """Summarize a single article in one LLM call.

    No chunk/reduce: the article is truncated to settings.max_article_chars,
    which is sized so one request stays inside the per-minute token budget at
    the configured RPM. Chunking two summaries together lost detail without
    helping the final digest (see docs/superpowers/plans/2026-10-24-...).

    Returns (summary_text, chunk_count, provider_used); chunk_count is kept at
    1 for schema compatibility.
    """
    if len(raw_text) > settings.max_article_chars:
        raw_text = raw_text[: settings.max_article_chars]

    summary = call_llm(
        prompt_manager.get_prompt(prompt_name).format(text=raw_text),
        max_tokens=settings.article_max_output_tokens,
    )
    return summary, 1, get_last_provider()


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

    source_footnote = "\n".join(source_list_lines)

    # PHASE 1 — Per-article story extraction. One small call per article so the
    # model only has to enumerate the stories in a single summary (2-15 stories),
    # which it does reliably. This guarantees every story from every article
    # survives, even on dense days / at 50+ articles.
    story_bullets = []
    for i, a in enumerate(articles, start=1):
        if on_progress:
            on_progress(f"Extracting stories from article {i}/{len(articles)}: {a['title'][:50]}")
        try:
            chunk = call_llm(
                prompt_manager.get_prompt(RSS_STORY_EXTRACT).format(
                    ref_num=i,
                    summary=a.get("summary_text") or "",
                ),
                provider=provider,
                model=model or settings.gemini_digest_model,
                max_tokens=4096,
                on_progress=on_progress,
            )
        except Exception as e:
            logger.warning(f"Story extraction failed for article #{a['id']}: {e}")
            # Fall back to a single bullet with the whole condensed summary so
            # the article is still represented rather than silently dropped.
            chunk = f"- **{a['title']}** — {(a.get('summary_text') or '')[:800]} [{i}]"
        story_bullets.append(chunk.strip())

    # PHASE 2 — Merge: organize the pre-extracted bullets into sections +
    # highlights + key takeaway. Stories are already explicit, so the model
    # only groups them (low risk of dropping anything).
    if on_progress: on_progress("Merging story bullets into the digest...")
    all_bullets = "\n\n".join(story_bullets)
    digest_text = call_llm(
        prompt_manager.get_prompt(DIGEST_MERGE).format(
            date=date_str,
            story_bullets=all_bullets,
        ),
        provider=provider,
        model=model or settings.gemini_digest_model,
        max_tokens=settings.llm_digest_max_output_tokens,
        on_progress=on_progress,
    )
    digest_text = _strip_placeholder_sections(digest_text)

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

    # Collapse blank lines between consecutive bullet items so they render as
    # one list block instead of one-item-per-list (renderer splits on \n\n).
    digest_text = re.sub(r'\n\n(?=[-*] )', '\n', digest_text)

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
# YouTube Daily Digest Generation
# ---------------------------------------------------------------------------


def _generate_youtube_daily_digest(
    conn, date_str: str, provider: str | None = None, model: str | None = None, on_progress=None
) -> None:
    """Generate (or regenerate) the YouTube daily digest for a given date."""
    videos = get_youtube_articles_for_date(conn, date_str)

    if not videos:
        if on_progress:
            on_progress("No YouTube videos for this date")
        logger.info(f"No summarized YouTube videos for {date_str}, skipping digest")
        return

    if on_progress:
        on_progress(f"Building YouTube digest prompt from {len(videos)} videos...")

    # Build numbered source list with URLs for citation footnotes & hyperlinks
    source_list_lines = []
    ref_urls = {}  # ref_number -> url
    for i, v in enumerate(videos, start=1):
        source_name = v.get('source_name', 'Unknown')
        title = v['title']
        url = v.get('url', '#')
        source_list_lines.append(f"[{i}] [{source_name} — {title}]({url})")
        ref_urls[i] = url

    source_footnote = "\n".join(source_list_lines)

    # PHASE 1 — Per-video topic extraction. One small call per video so every
    # distinct topic from every video is captured reliably.
    story_bullets = []
    for i, v in enumerate(videos, start=1):
        if on_progress:
            on_progress(f"Extracting topics from video {i}/{len(videos)}: {v['title'][:50]}")
        try:
            chunk = call_llm(
                _get_digest_extract_prompt(is_youtube=True).format(
                    ref_num=i,
                    summary=v.get("summary_text") or "",
                ),
                provider=provider,
                model=model or settings.gemini_digest_model,
                max_tokens=4096,
                on_progress=on_progress,
            )
        except Exception as e:
            logger.warning(f"Topic extraction failed for video #{v['id']}: {e}")
            chunk = f"- **{v['title']}** — {(v.get('summary_text') or '')[:800]} [{i}]"
        story_bullets.append(chunk.strip())

    # PHASE 2 — Merge: organize the pre-extracted topic bullets into the digest.
    if on_progress:
        on_progress("Merging topic bullets into the YouTube digest...")
    all_bullets = "\n\n".join(story_bullets)
    digest_text = call_llm(
        prompt_manager.get_prompt(DIGEST_MERGE).format(
            date=date_str,
            story_bullets=all_bullets,
        ),
        provider=provider,
        model=model or settings.gemini_digest_model,
        max_tokens=settings.llm_digest_max_output_tokens,
        on_progress=on_progress,
    )
    digest_text = _strip_placeholder_sections(digest_text)

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

    # Collapse blank lines between consecutive bullet items so they render as
    # one list block instead of one-item-per-list (renderer splits on \n\n).
    digest_text = re.sub(r'\n\n(?=[-*] )', '\n', digest_text)

    # Append source footnote with clickable links
    digest_text += f"\n\n## 📚 Sources\n\n{source_footnote}"

    if on_progress:
        on_progress("LLM responded, saving YouTube digest...")

    # Count unique channels
    unique_channels = len({v.get("source_id") for v in videos})

    # Generate title
    title = f"YouTube Daily Digest - {_format_date_pretty(date_str)}"

    digest_id = insert_youtube_digest(
        conn,
        date_str=date_str,
        title=title,
        summary_text=digest_text,
        video_count=len(videos),
        channel_count=unique_channels,
    )

    # Link videos to digest
    video_ids = [v["id"] for v in videos]
    link_videos_to_youtube_digest(conn, digest_id, video_ids)

    logger.info(
        f"YouTube digest generated for {date_str}: "
        f"{len(videos)} videos from {unique_channels} channels"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_digest_extract_prompt(is_youtube: bool = False) -> str:
    """Story-extraction prompt for digest Phase 1.

    YouTube uses its own more detailed variant (youtube_story_extract) because a
    YouTube digest covers only a handful of videos a day, so each video's block
    can be written much more thoroughly than an RSS article's.

    A missing template raises PromptNotFoundError; it does NOT silently fall
    back to the other variant, since that would change digest depth unnoticed.
    """
    name = YOUTUBE_STORY_EXTRACT if is_youtube else RSS_STORY_EXTRACT
    return prompt_manager.get_prompt(name)


def _today_ist_str() -> str:
    """Return today's date in IST as ISO string (YYYY-MM-DD)."""
    ist = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(ist).strftime("%Y-%m-%d")


_PLACEHOLDER_SECTION_RE = re.compile(r"^#{2,3}\s*Sections?\s*:?\s*$", re.IGNORECASE)


def _strip_placeholder_sections(text: str) -> str:
    """Remove a stray "## Sections" outline heading emitted by the merge model.

    Older merge prompts contained a literal ``## Sections`` line as an outline
    marker, and the model sometimes copied it into the digest. If the model
    nested real sections beneath it as ``###``, promote them to ``##`` so they
    still render at section level. Content is never dropped.
    """
    out: list[str] = []
    promote_next = False
    for line in text.splitlines():
        if _PLACEHOLDER_SECTION_RE.match(line):
            promote_next = True
            continue
        if promote_next and line.startswith("### "):
            line = "## " + line[4:]
        elif line.strip():
            promote_next = False
        out.append(line)
    return "\n".join(out)


def _format_date_pretty(date_str: str) -> str:
    """Convert ISO date to a pretty format, e.g. '29 May 2026'."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%d %B %Y")
    except ValueError:
        return date_str
