# Smart Digest Regeneration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After summarization, automatically regenerate stale digests within a 3-day IST window when new articles exist for a date that already has a digest.

**Architecture:** Extend the existing orphan-detection block in `run_summarization()` with a second query that finds dates where the digest exists but has unlinked summarized articles. If found within the 3-day window, call `_generate_daily_digest()` — the same function already used for regeneration.

**Tech Stack:** Python 3, SQLite, no new dependencies.

## Global Constraints

- No schema changes
- No new files
- 3-day window (today + yesterday + day-before-yesterday IST)
- Only regenerate if unlinked articles actually exist for that date
- Existing "no digest" orphan detection remains unchanged

---

### Task 1: Add stale-digest detection to `run_summarization()`

**File:**
- Modify: `app/summarizer/service.py` — insert new query + loop after existing orphan detection (~line 143)

**Description:** After the existing block that detects dates with no digest at all, add a second block that queries for dates within a 3-day IST window where the digest exists but some summarized RSS articles are not linked to it. For each such date, call `_generate_daily_digest()` to regenerate.

- [ ] **Step 1: Write the test**

Create a function to set up a stale-digest scenario and call `run_summarization`. Because `run_summarization` operates on raw articles, we can insert a pre-summarized article that is not linked to an existing digest, then verify the digest gets regenerated with the missing article included.

```python
# tests/test_stale_digest_regeneration.py
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest
from app.database import get_db, init_db
from app.summarizer.service import run_summarization
from unittest.mock import patch, ANY


@pytest.fixture
def db_conn():
    """Create an in-memory DB with the app schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    # Load schema from app
    from app.database import SCHEMA
    conn.executescript(SCHEMA)
    # Add source_type column if not in SCHEMA
    try:
        conn.execute("ALTER TABLE sources ADD COLUMN source_type TEXT DEFAULT 'rss'")
    except sqlite3.OperationalError:
        pass
    return conn


def make_ist_date(days_ago: int) -> str:
    """Return ISO date string for N days ago in IST."""
    ist = timezone(timedelta(hours=5, minutes=30))
    today = datetime.now(ist).date()
    return (today - timedelta(days=days_ago)).isoformat()


def test_regenerates_stale_digest_in_window(db_conn, monkeypatch):
    """When a summarized article exists for a date that already has a digest
    but isn't linked to it, run_summarization should regenerate that digest."""
    date_str = make_ist_date(1)  # yesterday — within 3-day window

    # Insert source
    db_conn.execute(
        "INSERT INTO sources (id, name, feed_url, source_type, is_active) VALUES (1, 'Test', 'http://example.com/feed', 'rss', 1)"
    )

    # Insert article already summarized but NOT linked to any digest
    db_conn.execute(
        """INSERT INTO articles (id, source_id, url, title, snippet, raw_text, summary_text, status, published_date_ist)
           VALUES (1, 1, 'http://example.com/1', 'Test Article', '', 'content', 'summary text', 'summarized', ?)""",
        (date_str,),
    )

    # Insert existing digest for that date (stale — only 0 articles declared)
    db_conn.execute(
        "INSERT INTO daily_digests (date, title, summary_text, article_count, source_count) VALUES (?, 'Old Digest', 'old content', 0, 0)",
        (date_str,),
    )

    # Monkey-patch get_db to return our in-memory connection
    monkeypatch.setattr("app.summarizer.service.get_db", lambda: db_conn)

    # Mock _generate_daily_digest to avoid LLM call
    from app.summarizer import service as svc
    original = svc._generate_daily_digest

    calls = []
    def fake_generate(conn, ds, provider=None, model=None, on_progress=None):
        calls.append(ds)

    monkeypatch.setattr(svc, "_generate_daily_digest", fake_generate)

    try:
        # Run summarization — there are no raw articles, but the stale-detection
        # should pick up article 1 not linked to the digest
        result = run_summarization()

        # Should have triggered regeneration for date_str
        assert date_str in calls, f"Expected digest regeneration for {date_str}, got {calls}"
        assert result["digest_generated"] is True
    finally:
        monkeypatch.setattr(svc, "_generate_daily_digest", original)


def test_skips_when_all_linked(db_conn, monkeypatch):
    """When all summarized articles are already linked to their digest,
    no regeneration should be triggered."""
    date_str = make_ist_date(1)

    db_conn.execute(
        "INSERT INTO sources (id, name, feed_url, source_type, is_active) VALUES (1, 'Test', 'http://example.com/feed', 'rss', 1)"
    )
    db_conn.execute(
        """INSERT INTO articles (id, source_id, url, title, snippet, raw_text, summary_text, status, published_date_ist)
           VALUES (1, 1, 'http://example.com/1', 'Test', '', 'content', 'summary', 'summarized', ?)""",
        (date_str,),
    )
    db_conn.execute(
        "INSERT INTO daily_digests (id, date, title, summary_text, article_count, source_count) VALUES (1, ?, 'Digest', 'content', 1, 1)",
        (date_str,),
    )
    # Article IS linked
    db_conn.execute(
        "INSERT INTO digest_articles (digest_id, article_id, inclusion_order) VALUES (1, 1, 1)"
    )

    monkeypatch.setattr("app.summarizer.service.get_db", lambda: db_conn)

    from app.summarizer import service as svc
    original = svc._generate_daily_digest
    calls = []
    monkeypatch.setattr(svc, "_generate_daily_digest", lambda conn, ds, **kw: calls.append(ds))

    try:
        run_summarization()
        assert date_str not in calls, f"Should NOT have regenerated, but did: {calls}"
    finally:
        monkeypatch.setattr(svc, "_generate_daily_digest", original)


def test_skips_outside_window(db_conn, monkeypatch):
    """Articles outside the 3-day window should NOT trigger auto-regeneration."""
    date_str = make_ist_date(4)  # 4 days ago — outside window

    db_conn.execute(
        "INSERT INTO sources (id, name, feed_url, source_type, is_active) VALUES (1, 'Test', 'http://example.com/feed', 'rss', 1)"
    )
    db_conn.execute(
        """INSERT INTO articles (id, source_id, url, title, snippet, raw_text, summary_text, status, published_date_ist)
           VALUES (1, 1, 'http://example.com/1', 'Test', '', 'content', 'summary', 'summarized', ?)""",
        (date_str,),
    )
    db_conn.execute(
        "INSERT INTO daily_digests (date, title, summary_text, article_count, source_count) VALUES (?, 'Old', 'content', 0, 0)",
        (date_str,),
    )

    monkeypatch.setattr("app.summarizer.service.get_db", lambda: db_conn)

    from app.summarizer import service as svc
    original = svc._generate_daily_digest
    calls = []
    monkeypatch.setattr(svc, "_generate_daily_digest", lambda conn, ds, **kw: calls.append(ds))

    try:
        run_summarization()
        assert date_str not in calls, f"Should NOT regenerate outside window, but did: {calls}"
    finally:
        monkeypatch.setattr(svc, "_generate_daily_digest", original)


def test_creates_digest_when_none_exists(db_conn, monkeypatch):
    """Existing behavior: date with articles but NO digest should still get one created."""
    date_str = make_ist_date(1)

    db_conn.execute(
        "INSERT INTO sources (id, name, feed_url, source_type, is_active) VALUES (1, 'Test', 'http://example.com/feed', 'rss', 1)"
    )
    db_conn.execute(
        """INSERT INTO articles (id, source_id, url, title, snippet, raw_text, summary_text, status, published_date_ist)
           VALUES (1, 1, 'http://example.com/1', 'Test', '', 'content', 'summary', 'summarized', ?)""",
        (date_str,),
    )
    # NO digest for this date

    monkeypatch.setattr("app.summarizer.service.get_db", lambda: db_conn)

    from app.summarizer import service as svc
    original = svc._generate_daily_digest
    calls = []
    monkeypatch.setattr(svc, "_generate_daily_digest", lambda conn, ds, **kw: calls.append(ds))

    try:
        run_summarization()
        assert date_str in calls, f"Should create digest for {date_str}, got {calls}"
    finally:
        monkeypatch.setattr(svc, "_generate_daily_digest", original)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd "C:/Users/pc/Documents/My Docs/Projects/personal-website"
python -m pytest tests/test_stale_digest_regeneration.py -v
```

Expected: 3 of 4 tests fail (the "no digest" test may pass since that's existing behavior). Tests for stale-digest detection should fail with assertions about missing regeneration calls.

- [ ] **Step 3: Implement the stale-digest detection**

In `app/summarizer/service.py`, after the existing orphan detection block (after the `for row in orphan_rows:` loop closes), add:

```python
        # ── Stale digest detection: dates within 3-day IST window that have
        # a digest but some summarized articles are not linked to it ──
        if "rss" in selected_types:
            ist = timezone(timedelta(hours=5, minutes=30))
            today_ist = datetime.now(ist).date()
            window_dates = [
                today_ist.isoformat(),
                (today_ist - timedelta(days=1)).isoformat(),
                (today_ist - timedelta(days=2)).isoformat(),
            ]
            stale_rows = conn.execute("""
                SELECT DISTINCT a.published_date_ist AS d
                FROM articles a
                JOIN sources s ON s.id = a.source_id
                WHERE s.source_type = 'rss'
                  AND a.status = 'summarized'
                  AND a.published_date_ist IN (?, ?, ?)
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
```

The `affected_dates["rss"]` set is already iterated below this point to call `_generate_daily_digest()` for each date — the stale dates flow into the same regeneration loop. No other changes needed.

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_stale_digest_regeneration.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Run existing test suite to check for regressions**

```bash
python -m pytest tests/ -v
```

Expected: all existing tests pass.

- [ ] **Step 6: Commit**

```bash
git add app/summarizer/service.py tests/test_stale_digest_regeneration.py docs/superpowers/specs/2026-07-25-smart-digest-regeneration-design.md docs/superpowers/plans/2026-07-25-smart-digest-regeneration.md
git commit -m "feat: auto-regenerate stale digests within 3-day IST window"
```
