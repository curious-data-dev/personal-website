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
    update_article_condensed_summary,
    get_articles_for_date,
    get_digest_for_date,
    insert_daily_digest,
    link_articles_to_digest,
    get_youtube_articles_for_date,
    insert_youtube_digest,
    link_videos_to_youtube_digest,
)
from app.summarizer.chunker import chunk_article
from app.summarizer.llm import (
    call_llm,
    get_last_provider,
    is_rate_limit_error,
    estimate_tokens,
)
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
    stats = {"articles_processed": 0, "articles_failed": 0, "articles_rate_limited": 0, "digest_generated": False, "digest_failed": 0}
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
                prompt_name = "youtube_summary" if is_youtube else "single_summary"
                reduce_prompt_name = "youtube_reduce_synthesis" if is_youtube else "reduce_synthesis"
                summary, chunk_count, provider = _summarize_article(raw_text, prompt_name=prompt_name, reduce_prompt_name=reduce_prompt_name)

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


def _summarize_article(raw_text: str, prompt_name: str = "single_summary", reduce_prompt_name: str = "reduce_synthesis") -> tuple[str, int, str]:
    """Summarize a single article using map-reduce if it's long.

    Returns (summary_text, chunk_count, provider_used).
    """
    # Truncate overly long articles
    if len(raw_text) > settings.max_article_chars:
        raw_text = raw_text[: settings.max_article_chars]

    # If short enough, summarize directly
    if len(raw_text) <= settings.chunk_size:
        summary = call_llm(prompt_manager.get_prompt(prompt_name).format(text=raw_text))
        return summary, 1, get_last_provider()

    # Map-Reduce: chunk → parallel summarize → synthesize
    chunks = chunk_article(raw_text)
    if not chunks:
        return "", 0, ""

    if len(chunks) == 1:
        summary = call_llm(prompt_manager.get_prompt(prompt_name).format(text=chunks[0]))
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

    # REDUCE phase: synthesize sub-summaries into one cohesive summary.
    # Group the sub-summaries so no single reduce request exceeds the
    # per-minute token budget (a request that can't fit the window can never
    # succeed, no matter how many times we retry). If the merged output of the
    # per-group results would itself exceed the budget, reduce again
    # hierarchically until a single summary remains.
    reduce_template = prompt_manager.get_prompt(reduce_prompt_name)
    budget = settings.llm_input_tokens_per_min
    prompt_overhead = estimate_tokens(reduce_template)

    def _fit_groups(texts: list[str]) -> list[list[str]]:
        """Pack texts into groups where each group fits the token budget.

        The template is included once per request, so overhead is counted once
        per group (not once per text).
        """
        groups: list[list[str]] = []
        current: list[str] = []
        current_tokens = prompt_overhead
        for s in texts:
            s_tokens = estimate_tokens(s)
            if current and current_tokens + s_tokens > budget:
                groups.append(current)
                current = [s]
                current_tokens = prompt_overhead + s_tokens
            else:
                current.append(s)
                current_tokens += s_tokens
        if current:
            groups.append(current)
        return groups

    results = sub_summaries
    max_passes = len(sub_summaries) + 1  # hard cap against pathological non-convergence
    for _ in range(max_passes):
        if len(results) <= 1:
            break
        groups = _fit_groups(results)
        results = [
            call_llm(reduce_template.format(sub_summaries="\n\n---\n\n".join(group)))
            for group in groups
        ]

    if not results:
        return "", 0, ""
    return results[0], len(chunks), get_last_provider()


def _get_condensed_summary(conn, article: dict) -> str:
    """Return a digest-ready condensed summary, caching it on the article row.

    The full article summary stays untouched (per-article detail preserved);
    this shorter form keeps the aggregated daily-digest prompt well under the
    per-minute token budget even for days with many articles.
    """
    cached = article.get("condensed_summary")
    if cached:
        return cached

    full = article.get("summary_text") or ""
    if len(full) <= settings.condense_target_chars:
        condensed = full
    else:
        try:
            condensed = call_llm(
                prompt_manager.get_prompt("condense_summary").format(text=full),
                model=settings.gemini_condense_model,
            )
        except Exception as e:
            logger.warning(f"Condensation failed for article #{article.get('id')}: {e}")
            condensed = full[: settings.condense_target_chars]
    update_article_condensed_summary(conn, article["id"], condensed)
    return condensed


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
                prompt_manager.get_prompt("digest_story_extract").format(
                    ref_num=i,
                    summary=_get_condensed_summary(conn, a),
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
            chunk = f"- **{a['title']}** — {(_get_condensed_summary(conn, a))[:800]} [{i}]"
        story_bullets.append(chunk.strip())

    # PHASE 2 — Merge: organize the pre-extracted bullets into sections +
    # highlights + key takeaway. Stories are already explicit, so the model
    # only groups them (low risk of dropping anything).
    if on_progress: on_progress("Merging story bullets into the digest...")
    all_bullets = "\n\n".join(story_bullets)
    digest_text = call_llm(
        prompt_manager.get_prompt("digest_merge").format(
            date=date_str,
            story_bullets=all_bullets,
        ),
        provider=provider,
        model=model or settings.gemini_digest_model,
        max_tokens=settings.llm_digest_max_output_tokens,
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
                    summary=_get_condensed_summary(conn, v),
                ),
                provider=provider,
                model=model or settings.gemini_digest_model,
                max_tokens=4096,
                on_progress=on_progress,
            )
        except Exception as e:
            logger.warning(f"Topic extraction failed for video #{v['id']}: {e}")
            chunk = f"- **{v['title']}** — {(_get_condensed_summary(conn, v))[:800]} [{i}]"
        story_bullets.append(chunk.strip())

    # PHASE 2 — Merge: organize the pre-extracted topic bullets into the digest.
    if on_progress:
        on_progress("Merging topic bullets into the YouTube digest...")
    all_bullets = "\n\n".join(story_bullets)
    digest_text = call_llm(
        prompt_manager.get_prompt("digest_merge").format(
            date=date_str,
            story_bullets=all_bullets,
        ),
        provider=provider,
        model=model or settings.gemini_digest_model,
        max_tokens=settings.llm_digest_max_output_tokens,
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

    YouTube uses its own more detailed variant (youtube_digest_story_extract)
    because a YouTube digest covers only a handful of videos a day, so each
    video's block can be written much more thoroughly than an RSS article's.
    Falls back to the shared RSS prompt if the YouTube file is missing.
    """
    if is_youtube:
        youtube_prompt = prompt_manager.get_prompt("youtube_digest_story_extract")
        if youtube_prompt:
            return youtube_prompt
    return prompt_manager.get_prompt("digest_story_extract")


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
