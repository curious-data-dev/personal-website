"""Kindle digest delivery.

After the daily run, send the previous day's RSS and YouTube digests to the
Kindle "Send to Kindle" address as EPUBs, plus any *older* digest that was
regenerated in that run (late-arriving articles refresh past digests, and the
reader should get those refreshed copies too).

Rules:
  * Yesterday's digest is always considered (the newest reliable edition).
  * Older regenerated digests are re-sent only when their text changed.
  * Today's digest is NEVER sent — it will still be refreshed later.
  * A content hash per (type, date) prevents duplicate emails.
"""

import hashlib
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

from app.config import settings
from app.database import (
    get_db,
    get_digest_for_date,
    get_kindle_send,
    get_youtube_digest_for_date,
    upsert_kindle_send,
)
from app.kindle.emailer import send_kindle_epub
from app.kindle.html2epub import convert_html_to_epub
from app.kindle.renderer import build_digest_html

logger = logging.getLogger(__name__)

# Kindle naming convention — the type prefix stays visible on the device.
TYPE_LABELS = {"rss": "RSS Digest", "youtube": "YouTube Digest"}


def _ist_today() -> str:
    ist = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(ist).strftime("%Y-%m-%d")


def _previous_day(date_str: str) -> str:
    return (
        datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=1)
    ).strftime("%Y-%m-%d")


def _pretty(date_str: str | None) -> str:
    """ISO date → '02 October 2026'."""
    if not date_str:
        return ""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%d %B %Y")
    except (ValueError, TypeError):
        return date_str


def _content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def build_digest_name(
    digest_type: str,
    date_str: str,
    refreshed: bool = False,
    refreshed_date: str | None = None,
) -> str:
    """Return the shared filename / EPUB-title / email-subject string.

    Examples:
        "RSS Digest - 02 October 2026"
        "YouTube Digest - 02 October 2026"
        "RSS Digest - 30 September 2026 (Updated 03 October 2026)"
    """
    name = f"{TYPE_LABELS[digest_type]} - {_pretty(date_str)}"
    if refreshed:
        name += f" (Updated {_pretty(refreshed_date or _ist_today())})"
    return name


def _get_digest(conn, digest_type: str, date_str: str) -> dict | None:
    if digest_type == "youtube":
        return get_youtube_digest_for_date(conn, date_str)
    return get_digest_for_date(conn, date_str)


def export_and_send_digest(
    conn,
    digest_type: str,
    date_str: str,
    *,
    refreshed: bool = False,
    refreshed_date: str | None = None,
    force: bool = False,
    dry_run: bool = False,
    recipient: str | None = None,
) -> dict:
    """Export one digest to HTML + EPUB and email it to Kindle.

    Returns a result dict with a ``status`` of ``sent``, ``built`` (dry run),
    ``skipped`` or ``failed``.
    """
    result: dict = {"type": digest_type, "date": date_str}
    digest = _get_digest(conn, digest_type, date_str)
    if not digest:
        return {**result, "status": "skipped", "reason": "no digest"}

    text = digest.get("summary_text") or ""
    if not text.strip():
        return {**result, "status": "skipped", "reason": "empty digest"}

    content_hash = _content_hash(text)
    name = build_digest_name(digest_type, date_str, refreshed, refreshed_date)

    if not force:
        previous = get_kindle_send(conn, digest_type, date_str)
        if previous and previous.get("content_hash") == content_hash:
            return {**result, "status": "skipped", "reason": "unchanged", "name": name}

    export_dir = Path(settings.kindle_export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)
    html_path = export_dir / f"{name}.html"
    epub_path = export_dir / f"{name}.epub"

    try:
        html = build_digest_html(digest, digest_type, name)
        html_path.write_text(html, encoding="utf-8")
        chapters = convert_html_to_epub(html, epub_path, title=name, author="Media Hub")
    except Exception as e:
        logger.exception(f"Failed to export {name}: {e}")
        return {**result, "status": "failed", "reason": f"export: {e}", "name": name}

    artifact = {
        **result,
        "name": name,
        "html": str(html_path),
        "epub": str(epub_path),
        "chapters": chapters,
    }

    if dry_run:
        return {**artifact, "status": "built"}

    if not send_kindle_epub(name, epub_path, recipient=recipient):
        return {**artifact, "status": "failed", "reason": "email send failed"}

    upsert_kindle_send(conn, digest_type, date_str, content_hash)
    conn.commit()
    return {**artifact, "status": "sent"}


def send_digests_to_kindle(
    regenerated: dict | None = None,
    today: str | None = None,
    *,
    force: bool = False,
    dry_run: bool = False,
    recipient: str | None = None,
) -> dict:
    """Send yesterday's digests plus any older regenerated digest.

    Args:
        regenerated: Optional ``{"rss": [dates], "youtube": [dates]}`` mapping
            of digests regenerated during the run. Dates >= today are ignored.
        today: Override for "today" (IST) — used by tests.
        force: Ignore the content-hash dedupe.
        dry_run: Build HTML/EPUB but do not email or record.
        recipient: Override the Kindle address.
    """
    today = today or _ist_today()
    yesterday = _previous_day(today)

    if not settings.kindle_enabled:
        return {"enabled": False, "reason": "kindle_enabled is false", "results": []}
    if not settings.kindle_email and not dry_run:
        return {"enabled": False, "reason": "kindle_email not configured", "results": []}

    candidates: dict[str, set[str]] = {"rss": {yesterday}, "youtube": {yesterday}}
    for digest_type, dates in (regenerated or {}).items():
        if digest_type not in candidates:
            continue
        for date_str in dates or []:
            # Never today (or the future): it will still be refreshed.
            if date_str and date_str < today:
                candidates[digest_type].add(date_str)

    results: list[dict] = []
    conn = get_db()
    try:
        for digest_type in ("rss", "youtube"):
            for date_str in sorted(candidates[digest_type]):
                results.append(
                    export_and_send_digest(
                        conn,
                        digest_type,
                        date_str,
                        refreshed=date_str < yesterday,
                        refreshed_date=today,
                        force=force,
                        dry_run=dry_run,
                        recipient=recipient,
                    )
                )
    finally:
        conn.close()

    logger.info(
        f"Kindle delivery for {today}: "
        + ", ".join(f"{r['type']} {r['date']}={r['status']}" for r in results)
    )
    return {"enabled": True, "today": today, "yesterday": yesterday, "results": results}
