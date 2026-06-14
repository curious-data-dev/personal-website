"""YouTube scraper service — discovers new videos via channel RSS feeds,
extracts transcripts, and stores them in the articles table.

Pipeline per channel:
1. Parse channel RSS feed (https://www.youtube.com/feeds/videos.xml?channel_id=UC...)
2. Filter to videos published within the lookback window
3. For each new video, fetch transcript via youtube-transcript-api
4. Store transcript as raw_text in articles (via existing insert_article)

Rate limiting is handled with configurable delays between requests.
"""

import logging
import re
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from typing import Any

import feedparser
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import TextFormatter

from app.config import settings
from app.database import (
    get_db,
    get_active_youtube_sources,
    insert_article,
    article_exists,
    update_source_last_fetched,
)

logger = logging.getLogger(__name__)

# Delays to stay under YouTube's rate-limit radar
DELAY_BETWEEN_CHANNELS_SEC = 30   # pause between processing each channel
DELAY_BETWEEN_TRANSCRIPTS_SEC = 10  # pause between transcript fetches


def _resolve_channel_id(handle_or_url: str) -> str | None:
    """Resolve a YouTube @handle or channel URL to a channel ID.

    Handles:
      - @Handle          → fetches the channel page, extracts UC... ID
      - UC...            → already a channel ID, return as-is
      - youtube.com/@... → extracts handle, then resolves
      - youtube.com/channel/UC... → extracts the ID directly
    """
    s = handle_or_url.strip()

    # Already a channel ID?
    if re.match(r"^UC[\w-]{20,}$", s):
        return s

    # Extract from full URL
    m = re.search(r"youtube\.com/channel/(UC[\w-]+)", s)
    if m:
        return m.group(1)

    # Extract handle
    m = re.search(r"youtube\.com/@([\w.-]+)", s)
    if m:
        handle = m.group(1)
    elif s.startswith("@"):
        handle = s[1:]
    else:
        handle = s

    # Fetch the channel page to find the externalId
    url = f"https://www.youtube.com/@{handle}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        matches = re.findall(r'"externalId"\s*:\s*"(UC[\w-]+)"', html)
        if matches:
            return matches[0]
        # Fallback: try channelId
        matches = re.findall(r'"channelId"\s*:\s*"(UC[\w-]+)"', html)
        if matches:
            return matches[0]
        logger.warning(f"Could not find channel ID for @{handle}")
        return None
    except Exception as e:
        logger.error(f"Failed to resolve @{handle}: {e}")
        return None


def _get_rss_url(channel_id: str) -> str:
    """Build the YouTube channel RSS feed URL."""
    return f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"


def _fetch_channel_videos(
    channel_id: str,
    since: datetime,
    until: datetime,
) -> list[dict[str, Any]]:
    """Fetch recent videos from a channel's RSS feed.

    Args:
        channel_id: YouTube channel ID (UC...).
        since: Only return videos published after this time (UTC).
        until: Only return videos published before this time (UTC).

    Returns:
        List of dicts with keys: video_id, title, url, published, snippet.
    """
    rss_url = _get_rss_url(channel_id)
    parsed = feedparser.parse(rss_url)

    if parsed.bozo and not parsed.entries:
        logger.warning(f"RSS parse warning for channel {channel_id}: {parsed.bozo_exception}")
        return []

    videos = []
    for entry in parsed.entries:
        video_id = entry.get("yt_videoid")
        if not video_id:
            continue

        # Parse published date
        published = None
        tp = entry.get("published_parsed")
        if tp and len(tp) >= 6:
            try:
                published = datetime(*tp[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                pass

        if published is None:
            # Try string parse
            raw = entry.get("published", "")
            if raw:
                try:
                    from email.utils import parsedate_to_datetime
                    published = parsedate_to_datetime(raw)
                except Exception:
                    continue

        if published is None:
            continue

        if published < since or published > until:
            continue

        # Extract video duration from RSS (media:content@duration or yt:duration in seconds)
        duration_seconds = None
        media_content = entry.get("media_content", [])
        if media_content:
            dur = media_content[0].get("duration")
            if dur:
                try:
                    duration_seconds = int(dur)
                except (ValueError, TypeError):
                    pass

        videos.append({
            "video_id": video_id,
            "title": entry.get("title", "Untitled"),
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "published": published,
            "snippet": _strip_html(entry.get("summary", entry.get("description", "")))[:500],
            "duration_seconds": duration_seconds,
        })

    return videos


def _fetch_transcript(video_id: str) -> str | None:
    """Fetch the transcript for a YouTube video.

    Prefers manually-created captions, falls back to auto-generated.
    Returns the transcript as plain text, or None if unavailable.
    """
    try:
        api = YouTubeTranscriptApi()
        transcript_list = api.list(video_id)

        # Prefer manual captions
        try:
            transcript = transcript_list.find_manually_created_transcript(
                ["en", "en-GB", "hi"]
            )
        except Exception:
            try:
                transcript = transcript_list.find_generated_transcript(
                    ["en", "en-GB", "hi"]
                )
            except Exception:
                logger.info(f"No English transcript available for video {video_id}")
                return None

        fetched = transcript.fetch()
        formatter = TextFormatter()
        text = formatter.format_transcript(fetched)

        # Remove empty/whitespace-only lines
        text = "\n".join(line for line in text.split("\n") if line.strip())
        return text

    except Exception as e:
        logger.warning(f"Transcript fetch failed for {video_id}: {e}")
        return None


def _strip_html(text: str) -> str:
    """Remove HTML tags from text."""
    clean = re.sub(r"<[^>]+>", " ", text)
    clean = re.sub(r"\s+", " ", clean)
    return clean.strip()


def run_youtube_scrape(
    channel_ids: list[str] | None = None,
    on_progress=None,
) -> dict:
    """Main entry point for the YouTube scraping pipeline.

    Args:
        channel_ids: Optional list of channel IDs to limit scraping.
                     If None, scrapes all active YouTube sources from DB.
        on_progress: Optional callback(status_message) for live progress.

    Returns:
        Dict with keys: channels_total, channels_success, channels_failed,
                        videos_new, videos_skipped, errors.
    """
    conn = get_db()
    stats = {
        "channels_total": 0,
        "channels_success": 0,
        "channels_failed": 0,
        "videos_new": 0,
        "videos_skipped": 0,
        "errors": [],
    }

    since = datetime.now(timezone.utc) - timedelta(hours=settings.lookback_hours)
    until = datetime.now(timezone.utc)

    try:
        # Get YouTube sources from DB
        if channel_ids:
            # Resolve handles/URLs to channel IDs
            resolved = []
            for cid in channel_ids:
                resolved_id = _resolve_channel_id(cid)
                if resolved_id:
                    resolved.append(resolved_id)
            if not resolved:
                return stats
            placeholders = ",".join("?" * len(resolved))
            feed_urls = [_get_rss_url(cid) for cid in resolved]
            rows = conn.execute(
                f"SELECT * FROM sources WHERE feed_url IN ({placeholders}) AND category='youtube' ORDER BY name",
                feed_urls,
            ).fetchall()
            sources = [dict(r) for r in rows]
        else:
            sources = get_active_youtube_sources(conn)

        stats["channels_total"] = len(sources)
        if not sources:
            logger.info("No active YouTube channels found")
            return stats

        total = len(sources)
        for idx, source in enumerate(sources):
            source_id = source["id"]
            source_name = source["name"]
            feed_url = source["feed_url"]

            # Extract channel ID from feed URL
            m = re.search(r"channel_id=(UC[\w-]+)", feed_url or "")
            channel_id = m.group(1) if m else None
            if not channel_id:
                logger.warning(f"Could not extract channel ID from feed_url: {feed_url}")
                stats["channels_failed"] += 1
                continue

            if on_progress:
                on_progress(f"YouTube: {source_name} ({idx + 1}/{total})")

            try:
                logger.info(f"Fetching YouTube channel: {source_name} ({channel_id})")
                videos = _fetch_channel_videos(channel_id, since, until)

                for video in videos:
                    video_url = video["url"]
                    if article_exists(conn, video_url):
                        stats["videos_skipped"] += 1
                        continue

                    if on_progress:
                        on_progress(
                            f"YouTube: {source_name} — fetching transcript for "
                            f"{video['title'][:50]}..."
                        )

                    # Rate-limit: pause between transcript fetches
                    time.sleep(DELAY_BETWEEN_TRANSCRIPTS_SEC)

                    transcript = _fetch_transcript(video["video_id"])

                    if transcript:
                        article_id = insert_article(
                            conn,
                            source_id=source_id,
                            url=video_url,
                            title=video["title"],
                            snippet=video["snippet"],
                            raw_text=transcript,
                            author=source_name,
                            published_at=video["published"],
                            status="raw",
                            duration_seconds=video.get("duration_seconds"),
                        )
                        if article_id:
                            stats["videos_new"] += 1
                            logger.info(
                                f"Stored transcript for {video['title'][:60]} "
                                f"({len(transcript)} chars)"
                            )
                    else:
                        # Store without transcript — still track the video
                        article_id = insert_article(
                            conn,
                            source_id=source_id,
                            url=video_url,
                            title=video["title"],
                            snippet=video["snippet"],
                            raw_text=video["snippet"],
                            author=source_name,
                            published_at=video["published"],
                            status="raw",
                            duration_seconds=video.get("duration_seconds"),
                        )
                        if article_id:
                            stats["videos_new"] += 1
                            logger.info(
                                f"Stored video (no transcript): {video['title'][:60]}"
                            )

                update_source_last_fetched(conn, source_id)
                stats["channels_success"] += 1

            except Exception as e:
                logger.error(f"Failed to process channel '{source_name}': {e}")
                stats["channels_failed"] += 1
                stats["errors"].append({
                    "channel": source_name,
                    "error": str(e),
                })

            conn.commit()

            # Rate-limit: pause between channels
            if idx < total - 1:
                time.sleep(DELAY_BETWEEN_CHANNELS_SEC)

    except Exception as e:
        logger.exception("YouTube scrape failed with unhandled error")
        raise
    finally:
        conn.close()

    logger.info(
        f"YouTube scrape complete: {stats['channels_success']}/{stats['channels_total']} "
        f"channels, {stats['videos_new']} new videos, {stats['videos_skipped']} skipped"
    )
    return stats
