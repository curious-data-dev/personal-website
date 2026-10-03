"""Tests for Kindle digest delivery: naming, export/EPUB, dedupe, scheduling."""

import zipfile
from datetime import datetime, timezone, timedelta

import pytest

import app.kindle.service as kindle
from app.config import settings
from app.database import (
    get_kindle_send,
    insert_daily_digest,
    insert_youtube_digest,
)


def ist_date(days_ago: int) -> str:
    ist = timezone(timedelta(hours=5, minutes=30))
    return (datetime.now(ist).date() - timedelta(days=days_ago)).isoformat()


@pytest.fixture
def kindle_env(tmp_path, monkeypatch):
    """Point exports at tmp and capture emails instead of sending them."""
    monkeypatch.setattr(settings, "kindle_enabled", True)
    monkeypatch.setattr(settings, "kindle_email", "reader@kindle.com")
    monkeypatch.setattr(settings, "kindle_export_dir", str(tmp_path / "exports"))

    sent = []

    def fake_send(subject, epub_path, recipient=None):
        from pathlib import Path

        assert Path(epub_path).exists(), "EPUB must exist before sending"
        sent.append({"subject": subject, "epub": str(epub_path), "to": recipient})
        return True

    monkeypatch.setattr(kindle, "send_kindle_epub", fake_send)
    return sent


# ---------------------------------------------------------------------------
# Naming convention
# ---------------------------------------------------------------------------


def test_build_digest_name_rss_and_youtube():
    assert kindle.build_digest_name("rss", "2026-10-02") == "RSS Digest - 02 October 2026"
    assert (
        kindle.build_digest_name("youtube", "2026-10-02")
        == "YouTube Digest - 02 October 2026"
    )


def test_build_digest_name_refreshed_includes_updated_suffix():
    name = kindle.build_digest_name(
        "youtube", "2026-09-30", refreshed=True, refreshed_date="2026-10-03"
    )
    assert name == "YouTube Digest - 30 September 2026 (Updated 03 October 2026)"


# ---------------------------------------------------------------------------
# Export + EPUB
# ---------------------------------------------------------------------------


def _seed_rss(isolated_db, date_str, text="## Today\n\nA story [1].\n\n## Sources\n\n[1] x"):
    conn = isolated_db.get_db()
    try:
        insert_daily_digest(conn, date_str, "Daily Digest", text, 1, 1)
        conn.commit()
    finally:
        conn.close()


def test_export_builds_html_and_epub(isolated_db, kindle_env, tmp_path):
    date_str = ist_date(1)
    _seed_rss(isolated_db, date_str)

    conn = isolated_db.get_db()
    try:
        result = kindle.export_and_send_digest(conn, "rss", date_str)
    finally:
        conn.close()

    assert result["status"] == "sent"
    assert result["name"] == f"RSS Digest - {kindle._pretty(date_str)}"
    assert len(kindle_env) == 1
    assert kindle_env[0]["subject"] == result["name"]

    from pathlib import Path

    html_path = Path(result["html"])
    epub_path = Path(result["epub"])
    assert html_path.exists() and epub_path.exists()

    # EPUB is a valid zip whose metadata title matches the naming convention.
    with zipfile.ZipFile(epub_path) as zf:
        opf = next(n for n in zf.namelist() if n.endswith(".opf"))
        content = zf.read(opf).decode("utf-8")
    assert result["name"] in content


def test_export_dedupes_unchanged_content(isolated_db, kindle_env):
    date_str = ist_date(1)
    _seed_rss(isolated_db, date_str)

    conn = isolated_db.get_db()
    try:
        first = kindle.export_and_send_digest(conn, "rss", date_str)
        second = kindle.export_and_send_digest(conn, "rss", date_str)
    finally:
        conn.close()

    assert first["status"] == "sent"
    assert second["status"] == "skipped"
    assert second["reason"] == "unchanged"
    assert len(kindle_env) == 1


def test_export_resends_when_content_changes(isolated_db, kindle_env):
    date_str = ist_date(1)
    _seed_rss(isolated_db, date_str, text="## Today\n\nOriginal text [1]")

    conn = isolated_db.get_db()
    try:
        kindle.export_and_send_digest(conn, "rss", date_str)
        # Digest gets refreshed with new content.
        insert_daily_digest(conn, date_str, "Daily Digest", "## Today\n\nNEW text [1]", 2, 1)
        conn.commit()
        again = kindle.export_and_send_digest(conn, "rss", date_str)
        stored = get_kindle_send(conn, "rss", date_str)
    finally:
        conn.close()

    assert again["status"] == "sent"
    assert len(kindle_env) == 2
    assert stored["content_hash"] == kindle._content_hash("## Today\n\nNEW text [1]")


def test_dry_run_builds_but_does_not_send_or_record(isolated_db, kindle_env):
    date_str = ist_date(1)
    _seed_rss(isolated_db, date_str)

    from pathlib import Path

    conn = isolated_db.get_db()
    try:
        result = kindle.export_and_send_digest(conn, "rss", date_str, dry_run=True)
        stored = get_kindle_send(conn, "rss", date_str)
    finally:
        conn.close()

    assert result["status"] == "built"
    assert Path(result["epub"]).exists()
    assert kindle_env == []
    assert stored is None


# ---------------------------------------------------------------------------
# Scheduling rules
# ---------------------------------------------------------------------------


def test_sends_yesterday_but_never_today(isolated_db, kindle_env):
    yesterday = ist_date(1)
    today = ist_date(0)

    conn = isolated_db.get_db()
    try:
        insert_daily_digest(conn, yesterday, "R", "## Y\n\nrss yesterday", 1, 1)
        insert_youtube_digest(conn, yesterday, "Y", "## Y\n\nyt yesterday", 1, 1)
        insert_daily_digest(conn, today, "R", "## T\n\nrss today", 1, 1)
        insert_youtube_digest(conn, today, "Y", "## T\n\nyt today", 1, 1)
        conn.commit()

        summary = kindle.send_digests_to_kindle(regenerated={"rss": [today]})
    finally:
        conn.close()

    sent_dates = {(r["type"], r["date"]) for r in summary["results"] if r["status"] == "sent"}
    assert ("rss", yesterday) in sent_dates
    assert ("youtube", yesterday) in sent_dates
    assert all(d != today for _, d in sent_dates)
    assert len(kindle_env) == 2


def test_refreshed_older_digest_gets_updated_suffix(isolated_db, kindle_env):
    yesterday = ist_date(1)
    older = ist_date(3)

    conn = isolated_db.get_db()
    try:
        insert_daily_digest(conn, yesterday, "R", "## Y\n\nrss yesterday", 1, 1)
        insert_daily_digest(conn, older, "R", "## O\n\nrss refreshed", 1, 1)
        conn.commit()

        summary = kindle.send_digests_to_kindle(regenerated={"rss": [older]})
    finally:
        conn.close()

    by_date = {r["date"]: r for r in summary["results"] if r["type"] == "rss"}
    assert by_date[older]["status"] == "sent"
    assert by_date[older]["name"] == (
        f"RSS Digest - {kindle._pretty(older)} "
        f"(Updated {kindle._pretty(kindle._ist_today())})"
    )
    # Yesterday's normal send has no suffix.
    assert "(Updated" not in by_date[yesterday]["name"]


def test_missing_digest_is_skipped(isolated_db, kindle_env):
    conn = isolated_db.get_db()
    try:
        result = kindle.export_and_send_digest(conn, "youtube", "2020-01-01")
    finally:
        conn.close()

    assert result["status"] == "skipped"
    assert result["reason"] == "no digest"
    assert kindle_env == []


def test_disabled_short_circuits(isolated_db, kindle_env, monkeypatch):
    monkeypatch.setattr(settings, "kindle_enabled", False)
    summary = kindle.send_digests_to_kindle()
    assert summary["enabled"] is False
    assert summary["results"] == []
