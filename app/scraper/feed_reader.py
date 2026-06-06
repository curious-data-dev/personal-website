"""OPML parser and RSS feed fetcher.

Reads an OPML file exported from feed readers (Inoreader, Feedly, etc.)
and fetches recent entries from each RSS/Atom feed.
"""

import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Any

import feedparser

from app.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# OPML Parsing
# ---------------------------------------------------------------------------


def parse_opml(opml_path: str) -> list[dict[str, str]]:
    """Parse an OPML file and return a flat list of feed dicts.

    Each dict has: name, xmlUrl, htmlUrl, category
    """
    tree = ET.parse(opml_path)
    root = tree.getroot()

    feeds: list[dict[str, str]] = []
    body = root.find("body")
    if body is None:
        logger.warning("OPML file has no <body> element")
        return feeds

    _walk_outlines(body, feeds, parent_category="")
    logger.info(f"Parsed {len(feeds)} feeds from OPML: {opml_path}")
    return feeds


def _walk_outlines(
    element: ET.Element, feeds: list[dict[str, str]], parent_category: str
) -> None:
    """Recursively walk <outline> elements to collect feed URLs."""
    for outline in element.findall("outline"):
        xml_url = outline.get("xmlUrl")
        if xml_url:
            feeds.append({
                "name": outline.get("text") or outline.get("title", "Untitled"),
                "xmlUrl": xml_url,
                "htmlUrl": outline.get("htmlUrl", ""),
                "category": parent_category,
            })
        else:
            # Nested folder — recurse with that folder name as category
            cat = outline.get("text") or outline.get("title", parent_category)
            _walk_outlines(outline, feeds, cat)


# ---------------------------------------------------------------------------
# Feed Fetching
# ---------------------------------------------------------------------------


def fetch_feed_entries(
    feed_url: str,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[dict[str, Any]]:
    """Fetch entries from a single RSS/Atom feed.

    Args:
        feed_url: The RSS feed URL.
        since: Only return entries published after this time (UTC).
               Defaults to settings.lookback_hours ago.
        until: Only return entries published before this time (UTC).
               Defaults to now.
    """
    if since is None:
        since = datetime.now(timezone.utc) - timedelta(hours=settings.lookback_hours)
    if until is None:
        until = datetime.now(timezone.utc)

    parsed = feedparser.parse(feed_url)

    if parsed.bozo and not parsed.entries:
        logger.warning(f"Feed parse warning for {feed_url}: {parsed.bozo_exception}")
        return []

    entries: list[dict[str, Any]] = []
    for entry in parsed.entries:
        published = _parse_published(entry)
        if published is None:
            continue  # Can't filter without a date — skip
        if published < since or published > until:
            continue  # Outside the requested range

        entries.append({
            "title": entry.get("title", "Untitled"),
            "url": entry.get("link", ""),
            "snippet": _strip_html(entry.get("summary", entry.get("description", ""))),
            "author": entry.get("author", ""),
            "published": published,
        })

    logger.debug(f"Fetched {len(entries)} entries from {feed_url} ({since.date()} → {until.date()})")
    return entries


def _parse_published(entry: dict[str, Any]) -> datetime | None:
    """Extract and parse the published date from a feed entry."""
    for field in ("published_parsed", "updated_parsed"):
        tp = entry.get(field)
        if tp and len(tp) >= 6:
            try:
                return datetime(*tp[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                pass

    # Try string field
    for field in ("published", "updated"):
        raw = entry.get(field, "")
        if raw:
            try:
                from email.utils import parsedate_to_datetime
                return parsedate_to_datetime(raw)
            except Exception:
                pass

    return None


def _strip_html(text: str) -> str:
    """Remove HTML tags, return plain text."""
    import re
    clean = re.sub(r"<[^>]+>", " ", text)
    clean = re.sub(r"\s+", " ", clean)
    return clean.strip()
