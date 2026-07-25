"""Tests for stale-digest detection in run_summarization().

When a summarized article exists for a date that already has a digest
but isn't linked to it, run_summarization should regenerate that digest
(within a 3-day IST window).
"""
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

import app.summarizer.service as svc
from app.summarizer.service import run_summarization


def make_ist_date(days_ago: int) -> str:
    """Return ISO date string for N days ago in IST."""
    ist = timezone(timedelta(hours=5, minutes=30))
    today = datetime.now(ist).date()
    return (today - timedelta(days=days_ago)).isoformat()


# ---------------------------------------------------------------------------
# Stale digest within 3-day window → regeneration triggered
# ---------------------------------------------------------------------------


def test_regenerates_stale_digest_in_window(isolated_db, monkeypatch):
    """When a summarized article exists for a date that already has a digest
    but isn't linked to it, run_summarization should regenerate that digest."""
    date_str = make_ist_date(1)  # yesterday — within 3-day window

    conn = isolated_db.get_db()
    try:
        # Insert source
        conn.execute(
            "INSERT INTO sources (name, feed_url, source_type, is_active) "
            "VALUES ('Test', 'http://example.com/feed', 'rss', 1)"
        )
        source_id = conn.execute(
            "SELECT id FROM sources WHERE feed_url='http://example.com/feed'"
        ).fetchone()["id"]

        # Insert article already summarized but NOT linked to any digest
        conn.execute(
            """INSERT INTO articles (source_id, url, title, snippet, raw_text,
               summary_text, status, published_date_ist)
               VALUES (?, 'http://example.com/1', 'Test Article', '',
               'content text long enough for validation', 'summary text',
               'summarized', ?)""",
            (source_id, date_str),
        )

        # Insert existing digest for that date (stale — only 0 articles declared)
        conn.execute(
            "INSERT INTO daily_digests (date, title, summary_text, article_count, "
            "source_count) VALUES (?, 'Old Digest', 'old content', 0, 0)",
            (date_str,),
        )
        conn.commit()
    finally:
        conn.close()

    # Mock _generate_daily_digest to avoid LLM call
    original = svc._generate_daily_digest
    calls = []

    def fake_generate(conn, ds, provider=None, model=None, on_progress=None):
        calls.append(ds)

    monkeypatch.setattr(svc, "_generate_daily_digest", fake_generate)

    try:
        # Run summarization — there are no raw articles, but the stale-detection
        # should pick up article 1 not linked to the digest
        result = svc.run_summarization()

        # Should have triggered regeneration for date_str
        assert date_str in calls, (
            f"Expected digest regeneration for {date_str}, got {calls}"
        )
        assert result["digest_generated"] is True
    finally:
        monkeypatch.setattr(svc, "_generate_daily_digest", original)


# ---------------------------------------------------------------------------
# All articles already linked → no regeneration
# ---------------------------------------------------------------------------


def test_skips_when_all_linked(isolated_db, monkeypatch):
    """When all summarized articles are already linked to their digest,
    no regeneration should be triggered."""
    date_str = make_ist_date(1)

    conn = isolated_db.get_db()
    try:
        conn.execute(
            "INSERT INTO sources (name, feed_url, source_type, is_active) "
            "VALUES ('Test', 'http://example.com/feed', 'rss', 1)"
        )
        source_id = conn.execute(
            "SELECT id FROM sources WHERE feed_url='http://example.com/feed'"
        ).fetchone()["id"]

        conn.execute(
            """INSERT INTO articles (source_id, url, title, snippet, raw_text,
               summary_text, status, published_date_ist)
               VALUES (?, 'http://example.com/1', 'Test', '',
               'content text long enough', 'summary', 'summarized', ?)""",
            (source_id, date_str),
        )
        article_id = conn.execute(
            "SELECT id FROM articles WHERE url='http://example.com/1'"
        ).fetchone()["id"]

        conn.execute(
            "INSERT INTO daily_digests (id, date, title, summary_text, "
            "article_count, source_count) VALUES (1, ?, 'Digest', 'content', 1, 1)",
            (date_str,),
        )
        # Article IS linked
        conn.execute(
            "INSERT INTO digest_articles (digest_id, article_id, inclusion_order) "
            "VALUES (1, ?, 1)",
            (article_id,),
        )
        conn.commit()
    finally:
        conn.close()

    original = svc._generate_daily_digest
    calls = []

    def fake_generate(conn, ds, provider=None, model=None, on_progress=None):
        calls.append(ds)

    monkeypatch.setattr(svc, "_generate_daily_digest", fake_generate)

    try:
        svc.run_summarization()
        assert date_str not in calls, (
            f"Should NOT have regenerated, but did: {calls}"
        )
    finally:
        monkeypatch.setattr(svc, "_generate_daily_digest", original)


# ---------------------------------------------------------------------------
# Outside 3-day window → skipped
# ---------------------------------------------------------------------------


def test_skips_outside_window(isolated_db, monkeypatch):
    """Articles outside the 3-day window should NOT trigger auto-regeneration."""
    date_str = make_ist_date(4)  # 4 days ago — outside window

    conn = isolated_db.get_db()
    try:
        conn.execute(
            "INSERT INTO sources (name, feed_url, source_type, is_active) "
            "VALUES ('Test', 'http://example.com/feed', 'rss', 1)"
        )
        source_id = conn.execute(
            "SELECT id FROM sources WHERE feed_url='http://example.com/feed'"
        ).fetchone()["id"]

        conn.execute(
            """INSERT INTO articles (source_id, url, title, snippet, raw_text,
               summary_text, status, published_date_ist)
               VALUES (?, 'http://example.com/1', 'Test', '',
               'content text long enough', 'summary', 'summarized', ?)""",
            (source_id, date_str),
        )

        conn.execute(
            "INSERT INTO daily_digests (date, title, summary_text, "
            "article_count, source_count) VALUES (?, 'Old', 'content', 0, 0)",
            (date_str,),
        )
        conn.commit()
    finally:
        conn.close()

    original = svc._generate_daily_digest
    calls = []

    def fake_generate(conn, ds, provider=None, model=None, on_progress=None):
        calls.append(ds)

    monkeypatch.setattr(svc, "_generate_daily_digest", fake_generate)

    try:
        svc.run_summarization()
        assert date_str not in calls, (
            f"Should NOT regenerate outside window, but did: {calls}"
        )
    finally:
        monkeypatch.setattr(svc, "_generate_daily_digest", original)


# ---------------------------------------------------------------------------
# Existing behavior: dates with no digest at all still get one created
# ---------------------------------------------------------------------------


def test_creates_digest_when_none_exists(isolated_db, monkeypatch):
    """Existing behavior: date with articles but NO digest should still
    get one created (orphan detection)."""
    date_str = make_ist_date(1)

    conn = isolated_db.get_db()
    try:
        conn.execute(
            "INSERT INTO sources (name, feed_url, source_type, is_active) "
            "VALUES ('Test', 'http://example.com/feed', 'rss', 1)"
        )
        source_id = conn.execute(
            "SELECT id FROM sources WHERE feed_url='http://example.com/feed'"
        ).fetchone()["id"]

        conn.execute(
            """INSERT INTO articles (source_id, url, title, snippet, raw_text,
               summary_text, status, published_date_ist)
               VALUES (?, 'http://example.com/1', 'Test', '',
               'content text long enough', 'summary', 'summarized', ?)""",
            (source_id, date_str),
        )
        # NO digest for this date
        conn.commit()
    finally:
        conn.close()

    original = svc._generate_daily_digest
    calls = []

    def fake_generate(conn, ds, provider=None, model=None, on_progress=None):
        calls.append(ds)

    monkeypatch.setattr(svc, "_generate_daily_digest", fake_generate)

    try:
        svc.run_summarization()
        assert date_str in calls, (
            f"Should create digest for {date_str}, got {calls}"
        )
    finally:
        monkeypatch.setattr(svc, "_generate_daily_digest", original)
