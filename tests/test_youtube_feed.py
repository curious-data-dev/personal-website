"""Tests for YouTube channel-feed discovery robustness (gzip + fail-loud)."""

import gzip
from datetime import datetime, timezone

import pytest

from app.database import get_db
from app.scraper.youtube import service

VALID_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns="http://www.w3.org/2005/Atom">
 <title>Test Channel</title>
 <entry>
  <yt:videoId>abc123XYZ</yt:videoId>
  <title>Video A</title>
  <link rel="alternate" href="https://www.youtube.com/watch?v=abc123XYZ"/>
  <published>2026-10-01T15:00:31+00:00</published>
 </entry>
</feed>
"""


class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_fetch_feed_bytes_decompresses_gzip(monkeypatch):
    raw = b"<feed>hello</feed>"
    compressed = gzip.compress(raw)
    monkeypatch.setattr(
        service.urllib.request, "urlopen", lambda *a, **k: _FakeResponse(compressed)
    )
    assert service._fetch_feed_bytes("http://example.test/feed") == raw


def test_fetch_feed_bytes_returns_plain_body(monkeypatch):
    body = b"<feed>plain</feed>"
    monkeypatch.setattr(
        service.urllib.request, "urlopen", lambda *a, **k: _FakeResponse(body)
    )
    assert service._fetch_feed_bytes("http://example.test/feed") == body


def test_fetch_channel_videos_raises_on_unparseable_feed(monkeypatch):
    """A corrupt/compressed-not-decoded feed must not look like 'no videos'."""
    # feedparser cannot parse raw gzip bytes -> bozo, zero entries.
    monkeypatch.setattr(
        service, "_fetch_feed_bytes", lambda url: gzip.compress(VALID_FEED)
    )
    with pytest.raises(service.FeedFetchError):
        service._fetch_channel_videos(
            "UCtest", datetime(2026, 9, 1, tzinfo=timezone.utc), datetime(2026, 10, 5, tzinfo=timezone.utc)
        )


def test_fetch_channel_videos_parses_valid_feed(monkeypatch):
    monkeypatch.setattr(service, "_fetch_feed_bytes", lambda url: VALID_FEED)
    videos = service._fetch_channel_videos(
        "UCtest", datetime(2026, 9, 1, tzinfo=timezone.utc), datetime(2026, 10, 5, tzinfo=timezone.utc)
    )
    assert len(videos) == 1
    assert videos[0]["video_id"] == "abc123XYZ"
    assert videos[0]["published"] == datetime(2026, 10, 1, 15, 0, 31, tzinfo=timezone.utc)


def test_run_youtube_scrape_marks_channel_failed_on_feed_error(isolated_db, monkeypatch):
    conn = get_db()
    conn.execute(
        """INSERT INTO sources (name, feed_url, site_url, category, source_type, is_active)
           VALUES (?, ?, '', 'youtube', 'youtube', 1)""",
        ("Broken Channel", "https://www.youtube.com/feeds/videos.xml?channel_id=UCbroken"),
    )
    conn.commit()
    source_id = conn.execute(
        "SELECT id FROM sources WHERE name='Broken Channel'"
    ).fetchone()["id"]
    conn.close()

    def _boom(*args, **kwargs):
        raise service.FeedFetchError("simulated parse failure")

    monkeypatch.setattr(service, "_fetch_channel_videos", _boom)

    stats = service.run_youtube_scrape(source_ids=[source_id], defer_transcripts=True)

    assert stats["channels_failed"] == 1
    assert stats["channels_success"] == 0
    assert stats["videos_new"] == 0
    assert stats["errors"] and "simulated" in stats["errors"][0]["error"]

    conn = get_db()
    row = conn.execute(
        "SELECT last_fetch_status, last_fetch_error FROM sources WHERE id=?", (source_id,)
    ).fetchone()
    conn.close()
    assert row["last_fetch_status"] == "failed"
    assert "simulated" in (row["last_fetch_error"] or "")


def test_run_youtube_scrape_stores_discovered_video(isolated_db, monkeypatch):
    conn = get_db()
    conn.execute(
        """INSERT INTO sources (name, feed_url, site_url, category, source_type, is_active)
           VALUES (?, ?, '', 'youtube', 'youtube', 1)""",
        ("Good Channel", "https://www.youtube.com/feeds/videos.xml?channel_id=UCgood"),
    )
    conn.commit()
    source_id = conn.execute(
        "SELECT id FROM sources WHERE name='Good Channel'"
    ).fetchone()["id"]
    conn.close()

    monkeypatch.setattr(service, "_fetch_feed_bytes", lambda url: VALID_FEED)

    stats = service.run_youtube_scrape(
        source_ids=[source_id], start_date="2026-09-28", defer_transcripts=True
    )

    assert stats["videos_new"] == 1
    assert stats["channels_success"] == 1

    conn = get_db()
    article = conn.execute(
        "SELECT status, url FROM articles WHERE source_id=?", (source_id,)
    ).fetchone()
    job = conn.execute("SELECT status FROM transcript_jobs").fetchone()
    conn.close()
    assert article["status"] == "pending_transcript"
    assert article["url"] == "https://www.youtube.com/watch?v=abc123XYZ"
    assert job["status"] == "pending"


# ---------------------------------------------------------------------------
# YouTube Data API v3 discovery (option 1)
# ---------------------------------------------------------------------------

API_RESPONSE = {
    "items": [
        {
            "snippet": {
                "title": "New Video",
                "resourceId": {"videoId": "apiNEW1234"},
                "publishedAt": "2026-10-15T10:00:00Z",
                "description": "new description",
            },
            "contentDetails": {"videoPublishedAt": "2026-10-15T09:00:00Z"},
        },
        {
            "snippet": {
                "title": "Old Video",
                "resourceId": {"videoId": "apiOLD1234"},
                "publishedAt": "2026-09-01T10:00:00Z",
            },
            "contentDetails": {"videoPublishedAt": "2026-09-01T09:00:00Z"},
        },
    ]
}


def test_uploads_playlist_id():
    assert service._uploads_playlist_id("UCqW8jxh4tH1Z1sWPbkGWL4g") == "UUqW8jxh4tH1Z1sWPbkGWL4g"


def test_api_discovery_parses_and_filters(monkeypatch):
    monkeypatch.setattr(service.settings, "youtube_api_key", "test-key")
    monkeypatch.setattr(service, "_youtube_api_get", lambda path, params: API_RESPONSE)

    videos = service._fetch_channel_videos(
        "UCtest", datetime(2026, 10, 10, tzinfo=timezone.utc),
        datetime(2026, 10, 20, tzinfo=timezone.utc),
    )

    assert len(videos) == 1
    assert videos[0]["video_id"] == "apiNEW1234"
    assert videos[0]["published"] == datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc)


def test_api_preferred_when_key_set(monkeypatch):
    monkeypatch.setattr(service.settings, "youtube_api_key", "test-key")
    monkeypatch.setattr(service, "_youtube_api_get", lambda path, params: API_RESPONSE)
    monkeypatch.setattr(
        service, "_fetch_feed_bytes",
        lambda url: (_ for _ in ()).throw(AssertionError("RSS should not be used")),
    )

    videos = service._fetch_channel_videos(
        "UCtest", datetime(2026, 10, 10, tzinfo=timezone.utc),
        datetime(2026, 10, 20, tzinfo=timezone.utc),
    )
    assert [v["video_id"] for v in videos] == ["apiNEW1234"]


def test_api_failure_falls_back_to_rss(monkeypatch):
    monkeypatch.setattr(service.settings, "youtube_api_key", "test-key")

    def _boom(path, params):
        raise service.FeedFetchError("quota exceeded")

    monkeypatch.setattr(service, "_youtube_api_get", _boom)
    monkeypatch.setattr(service, "_fetch_feed_bytes", lambda url: VALID_FEED)

    videos = service._fetch_channel_videos(
        "UCtest", datetime(2026, 9, 1, tzinfo=timezone.utc),
        datetime(2026, 10, 5, tzinfo=timezone.utc),
    )
    assert [v["video_id"] for v in videos] == ["abc123XYZ"]


def test_no_key_uses_rss(monkeypatch):
    monkeypatch.setattr(service.settings, "youtube_api_key", "")
    monkeypatch.setattr(service, "_fetch_feed_bytes", lambda url: VALID_FEED)
    monkeypatch.setattr(
        service, "_youtube_api_get",
        lambda path, params: (_ for _ in ()).throw(AssertionError("API should not be used")),
    )

    videos = service._fetch_channel_videos(
        "UCtest", datetime(2026, 9, 1, tzinfo=timezone.utc),
        datetime(2026, 10, 5, tzinfo=timezone.utc),
    )
    assert [v["video_id"] for v in videos] == ["abc123XYZ"]

