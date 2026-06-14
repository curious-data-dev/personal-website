"""SQLite database layer — init, connection, and CRUD helpers.

Uses raw sqlite3 from stdlib. No ORM. One file. Simple.
"""

import sqlite3
import json
from datetime import datetime, date
from pathlib import Path
from typing import Any

from app.config import settings

DB_PATH = Path(settings.data_dir) / "aggregator.db"

# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------


def get_db() -> sqlite3.Connection:
    """Return a new connection. Caller must close it."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


# ---------------------------------------------------------------------------
# Schema initialisation
# ---------------------------------------------------------------------------


def init_db() -> None:
    """Create tables if they don't exist. Safe to call on every startup."""
    conn = get_db()
    try:
        conn.executescript(SCHEMA)
        _run_migrations(conn)
        conn.commit()
    finally:
        conn.close()

def _run_migrations(conn: sqlite3.Connection) -> None:
    """Add columns that may be missing from older schemas."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(articles)")}
    if "llm_provider" not in cols:
        conn.execute("ALTER TABLE articles ADD COLUMN llm_provider TEXT")
        conn.commit()
    if "duration_seconds" not in cols:
        conn.execute("ALTER TABLE articles ADD COLUMN duration_seconds INTEGER")
        conn.commit()


SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    feed_url        TEXT    NOT NULL UNIQUE,
    site_url        TEXT,
    category        TEXT,
    is_active       INTEGER DEFAULT 1,
    last_fetched_at TIMESTAMP,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS articles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id       INTEGER REFERENCES sources(id),
    url             TEXT    NOT NULL UNIQUE,
    title           TEXT    NOT NULL,
    snippet         TEXT,
    raw_text        TEXT,
    summary_text    TEXT,
    author          TEXT,
    published_at    TIMESTAMP,
    fetched_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status          TEXT    DEFAULT 'raw',
    chunk_count     INTEGER DEFAULT 0,
    llm_provider    TEXT,
    error_message   TEXT
);

CREATE TABLE IF NOT EXISTS daily_digests (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    date            DATE    NOT NULL UNIQUE,
    title           TEXT,
    summary_text    TEXT,
    article_count   INTEGER DEFAULT 0,
    source_count    INTEGER DEFAULT 0,
    status          TEXT    DEFAULT 'generated',
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS digest_articles (
    digest_id       INTEGER REFERENCES daily_digests(id),
    article_id      INTEGER REFERENCES articles(id),
    inclusion_order INTEGER,
    PRIMARY KEY (digest_id, article_id)
);

CREATE TABLE IF NOT EXISTS scrape_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TIMESTAMP,
    finished_at     TIMESTAMP,
    feeds_total     INTEGER DEFAULT 0,
    feeds_success   INTEGER DEFAULT 0,
    feeds_failed    INTEGER DEFAULT 0,
    articles_new    INTEGER DEFAULT 0,
    articles_skipped INTEGER DEFAULT 0,
    error_details   TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS youtube_digests (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    date            DATE    NOT NULL UNIQUE,
    title           TEXT,
    summary_text    TEXT,
    video_count     INTEGER DEFAULT 0,
    channel_count   INTEGER DEFAULT 0,
    status          TEXT    DEFAULT 'generated',
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS youtube_digest_videos (
    digest_id       INTEGER REFERENCES youtube_digests(id),
    article_id      INTEGER REFERENCES articles(id),
    inclusion_order INTEGER,
    PRIMARY KEY (digest_id, article_id)
);

CREATE INDEX IF NOT EXISTS idx_articles_status ON articles(status);
CREATE INDEX IF NOT EXISTS idx_articles_source_id ON articles(source_id);
CREATE INDEX IF NOT EXISTS idx_articles_fetched_at ON articles(fetched_at);
CREATE INDEX IF NOT EXISTS idx_daily_digests_date ON daily_digests(date);
CREATE INDEX IF NOT EXISTS idx_youtube_digests_date ON youtube_digests(date);
"""

# ---------------------------------------------------------------------------
# Sources CRUD
# ---------------------------------------------------------------------------


def upsert_source(conn: sqlite3.Connection, name: str, feed_url: str,
                  site_url: str = "", category: str = "") -> int:
    """Insert a source or update its name if feed_url already exists."""
    cur = conn.execute(
        """INSERT INTO sources (name, feed_url, site_url, category)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(feed_url) DO UPDATE SET
               name = excluded.name,
               site_url = excluded.site_url,
               category = excluded.category""",
        (name, feed_url, site_url, category),
    )
    return cur.lastrowid


def get_active_sources(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM sources WHERE is_active = 1 ORDER BY category, name"
    ).fetchall()
    return [dict(r) for r in rows]


def get_all_sources(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM sources ORDER BY category, name"
    ).fetchall()
    return [dict(r) for r in rows]


def update_source_last_fetched(conn: sqlite3.Connection, source_id: int) -> None:
    conn.execute(
        "UPDATE sources SET last_fetched_at = ? WHERE id = ?",
        (datetime.utcnow(), source_id),
    )


def update_source_active(conn: sqlite3.Connection, source_id: int, is_active: bool) -> None:
    conn.execute(
        "UPDATE sources SET is_active = ? WHERE id = ?",
        (1 if is_active else 0, source_id),
    )


def delete_source(conn: sqlite3.Connection, source_id: int) -> int:
    """Delete a source and all its articles. Returns number of articles deleted."""
    conn.execute(
        "DELETE FROM digest_articles WHERE article_id IN "
        "(SELECT id FROM articles WHERE source_id = ?)",
        (source_id,),
    )
    conn.execute(
        "DELETE FROM youtube_digest_videos WHERE article_id IN "
        "(SELECT id FROM articles WHERE source_id = ?)",
        (source_id,),
    )
    cur = conn.execute(
        "DELETE FROM articles WHERE source_id = ?",
        (source_id,),
    )
    articles_deleted = cur.rowcount
    conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
    return articles_deleted


def get_raw_articles_for_source(
    conn: sqlite3.Connection, source_id: int, limit: int = 50
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM articles WHERE status = 'raw' AND source_id = ? "
        "ORDER BY fetched_at DESC LIMIT ?",
        (source_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def update_source(
    conn: sqlite3.Connection,
    source_id: int,
    name: str | None = None,
    feed_url: str | None = None,
    site_url: str | None = None,
    category: str | None = None,
) -> None:
    """Update editable fields on a source. Only provided fields are changed."""
    fields = []
    params = []
    if name is not None:
        fields.append("name = ?")
        params.append(name)
    if feed_url is not None:
        fields.append("feed_url = ?")
        params.append(feed_url)
    if site_url is not None:
        fields.append("site_url = ?")
        params.append(site_url)
    if category is not None:
        fields.append("category = ?")
        params.append(category)
    if fields:
        params.append(source_id)
        conn.execute(
            f"UPDATE sources SET {', '.join(fields)} WHERE id = ?",
            params,
        )


def get_articles_for_source(
    conn: sqlite3.Connection, source_id: int, limit: int = 5
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, title, url, summary_text, status, fetched_at "
        "FROM articles WHERE source_id = ? "
        "ORDER BY fetched_at DESC LIMIT ?",
        (source_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Articles CRUD
# ---------------------------------------------------------------------------


def insert_article(conn: sqlite3.Connection, **kwargs) -> int | None:
    """Insert an article. Returns its id, or None if URL already exists."""
    try:
        cur = conn.execute(
            """INSERT INTO articles
               (source_id, url, title, snippet, raw_text, author, published_at, fetched_at, status, duration_seconds)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                kwargs.get("source_id"),
                kwargs["url"],
                kwargs["title"],
                kwargs.get("snippet", ""),
                kwargs.get("raw_text", ""),
                kwargs.get("author", ""),
                kwargs.get("published_at"),
                kwargs.get("fetched_at") or datetime.utcnow(),
                kwargs.get("status", "raw"),
                kwargs.get("duration_seconds"),
            ),
        )
        return cur.lastrowid
    except sqlite3.IntegrityError:
        return None


def article_exists(conn: sqlite3.Connection, url: str) -> bool:
    row = conn.execute("SELECT 1 FROM articles WHERE url = ?", (url,)).fetchone()
    return row is not None


def get_raw_articles(conn: sqlite3.Connection, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM articles WHERE status = 'raw' ORDER BY fetched_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def update_article_status(
    conn: sqlite3.Connection, article_id: int, status: str, error_message: str = ""
) -> None:
    conn.execute(
        "UPDATE articles SET status = ?, error_message = ? WHERE id = ?",
        (status, error_message, article_id),
    )


def update_article_summary(
    conn: sqlite3.Connection, article_id: int, summary_text: str,
    chunk_count: int = 0, llm_provider: str = ""
) -> None:
    conn.execute(
        """UPDATE articles
           SET summary_text = ?, chunk_count = ?, llm_provider = ?, status = 'summarized'
           WHERE id = ?""",
        (summary_text, chunk_count, llm_provider, article_id),
    )


def get_article(conn: sqlite3.Connection, article_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
    return dict(row) if row else None


def get_articles_for_date(
    conn: sqlite3.Connection, date_str: str
) -> list[dict[str, Any]]:
    """Get all summarized RSS articles fetched on a given date (IST day).

    Excludes YouTube sources so RSS digests don't accidentally include video summaries.
    """
    rows = conn.execute(
        """SELECT a.*, s.name as source_name, s.category as source_category
           FROM articles a
           JOIN sources s ON a.source_id = s.id
           WHERE a.status = 'summarized'
             AND date(a.fetched_at) = date(?)
             AND (s.category IS NULL OR s.category != 'youtube')
           ORDER BY a.fetched_at DESC""",
        (date_str,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_recent_articles(
    conn: sqlite3.Connection, limit: int = 30
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT a.*, s.name as source_name
           FROM articles a
           JOIN sources s ON a.source_id = s.id
           WHERE a.status = 'summarized'
             AND (s.category IS NULL OR s.category != 'youtube')
           ORDER BY a.fetched_at DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Daily Digests CRUD
# ---------------------------------------------------------------------------


def insert_daily_digest(
    conn: sqlite3.Connection,
    date_str: str,
    title: str,
    summary_text: str,
    article_count: int,
    source_count: int,
) -> int:
    cur = conn.execute(
        """INSERT INTO daily_digests (date, title, summary_text, article_count, source_count)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(date) DO UPDATE SET
               title = excluded.title,
               summary_text = excluded.summary_text,
               article_count = excluded.article_count,
               source_count = excluded.source_count,
               status = 'generated',
               updated_at = CURRENT_TIMESTAMP""",
        (date_str, title, summary_text, article_count, source_count),
    )
    if cur.lastrowid:
        return cur.lastrowid
    # ON CONFLICT UPDATE doesn't set lastrowid — fetch the existing ID
    row = conn.execute(
        "SELECT id FROM daily_digests WHERE date = ?", (date_str,)
    ).fetchone()
    return row[0] if row else 0


def get_digest_for_date(
    conn: sqlite3.Connection, date_str: str
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM daily_digests WHERE date = ?", (date_str,)
    ).fetchone()
    return dict(row) if row else None


def get_all_digests(
    conn: sqlite3.Connection, year: int | None = None, month: int | None = None
) -> list[dict[str, Any]]:
    query = "SELECT * FROM daily_digests"
    params = []
    conditions = []

    if year:
        conditions.append("strftime('%Y', date) = ?")
        params.append(str(year))
    if month and month > 0:
        conditions.append("strftime('%m', date) = ?")
        params.append(f"{int(month):02d}")

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY date DESC"

    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def link_articles_to_digest(
    conn: sqlite3.Connection, digest_id: int, article_ids: list[int]
) -> None:
    """Link articles to a digest (deletes old links first)."""
    conn.execute("DELETE FROM digest_articles WHERE digest_id = ?", (digest_id,))
    for i, aid in enumerate(article_ids):
        conn.execute(
            "INSERT INTO digest_articles (digest_id, article_id, inclusion_order) VALUES (?, ?, ?)",
            (digest_id, aid, i + 1),
        )


def get_digest_articles(
    conn: sqlite3.Connection, digest_id: int
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT a.*, s.name as source_name, s.category as source_category
           FROM digest_articles da
           JOIN articles a ON da.article_id = a.id
           JOIN sources s ON a.source_id = s.id
           WHERE da.digest_id = ?
           ORDER BY da.inclusion_order""",
        (digest_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_digest_years(conn: sqlite3.Connection) -> list[int]:
    rows = conn.execute(
        "SELECT DISTINCT strftime('%Y', date) as year FROM daily_digests ORDER BY year DESC"
    ).fetchall()
    return [int(r["year"]) for r in rows]


# ---------------------------------------------------------------------------
# Scrape Log
# ---------------------------------------------------------------------------


def start_scrape_log(conn: sqlite3.Connection) -> int:
    cur = conn.execute(
        "INSERT INTO scrape_log (started_at, feeds_total) VALUES (?, 0)",
        (datetime.utcnow(),),
    )
    return cur.lastrowid


def finish_scrape_log(
    conn: sqlite3.Connection, log_id: int, **counts
) -> None:
    """Update scrape log with final counts."""
    conn.execute(
        """UPDATE scrape_log
           SET finished_at = ?,
               feeds_total = ?, feeds_success = ?, feeds_failed = ?,
               articles_new = ?, articles_skipped = ?,
               error_details = ?
           WHERE id = ?""",
        (
            datetime.utcnow(),
            counts.get("feeds_total", 0),
            counts.get("feeds_success", 0),
            counts.get("feeds_failed", 0),
            counts.get("articles_new", 0),
            counts.get("articles_skipped", 0),
            json.dumps(counts.get("errors", [])),
            log_id,
        ),
    )


def get_last_scrape(conn: sqlite3.Connection) -> dict[str, Any] | None:
    """Return info about the most recent scrape run."""
    row = conn.execute(
        "SELECT * FROM scrape_log ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None

def get_adjacent_dates(
    conn: sqlite3.Connection, date_str: str
) -> tuple[str | None, str | None]:
    """Return (prev_date, next_date) for digest navigation."""
    prev_row = conn.execute(
        "SELECT date FROM daily_digests WHERE date < ? ORDER BY date DESC LIMIT 1",
        (date_str,),
    ).fetchone()
    next_row = conn.execute(
        "SELECT date FROM daily_digests WHERE date > ? ORDER BY date ASC LIMIT 1",
        (date_str,),
    ).fetchone()
    return (
        prev_row["date"] if prev_row else None,
        next_row["date"] if next_row else None,
    )


# ---------------------------------------------------------------------------
# YouTube-specific helpers — reuses the sources and articles tables
# with category='youtube' to distinguish from RSS feeds.
# ---------------------------------------------------------------------------


def get_youtube_sources(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Return all YouTube channel sources (active + inactive)."""
    rows = conn.execute(
        "SELECT * FROM sources WHERE category = 'youtube' ORDER BY name"
    ).fetchall()
    return [dict(r) for r in rows]


def get_active_youtube_sources(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Return YouTube channels with is_active=1."""
    rows = conn.execute(
        "SELECT * FROM sources WHERE category = 'youtube' AND is_active = 1 ORDER BY name"
    ).fetchall()
    return [dict(r) for r in rows]


def upsert_youtube_source(
    conn: sqlite3.Connection,
    name: str,
    channel_id: str,
    channel_url: str = "",
) -> int:
    """Insert or update a YouTube channel source.

    Uses feed_url as the RSS feed URL derived from the channel ID.
    Returns the source id.
    """
    feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    row = conn.execute(
        "SELECT id FROM sources WHERE feed_url = ?", (feed_url,)
    ).fetchone()
    if row:
        conn.execute(
            "UPDATE sources SET name=?, site_url=?, is_active=1 WHERE id=?",
            (name, channel_url, row["id"]),
        )
        return row["id"]
    else:
        cur = conn.execute(
            """INSERT INTO sources (name, feed_url, site_url, category, is_active)
               VALUES (?, ?, ?, 'youtube', 1)""",
            (name, feed_url, channel_url),
        )
        return cur.lastrowid


def get_youtube_articles_for_channel(
    conn: sqlite3.Connection, source_id: int, limit: int = 50
) -> list[dict[str, Any]]:
    """Get summarized YouTube articles for a specific channel."""
    rows = conn.execute(
        """SELECT a.*, s.name as source_name
           FROM articles a
           JOIN sources s ON a.source_id = s.id
           WHERE a.source_id = ?
             AND s.category = 'youtube'
             AND a.status = 'summarized'
           ORDER BY a.published_at DESC
           LIMIT ?""",
        (source_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_youtube_articles_for_date(
    conn: sqlite3.Connection, date_str: str
) -> list[dict[str, Any]]:
    """Get summarized YouTube articles for a specific date."""
    rows = conn.execute(
        """SELECT a.*, s.name as source_name
           FROM articles a
           JOIN sources s ON a.source_id = s.id
           WHERE s.category = 'youtube'
             AND a.status = 'summarized'
             AND date(a.fetched_at) = ?
           ORDER BY a.published_at DESC""",
        (date_str,),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# YouTube Digests CRUD
# ---------------------------------------------------------------------------


def insert_youtube_digest(
    conn: sqlite3.Connection,
    date_str: str,
    title: str,
    summary_text: str,
    video_count: int,
    channel_count: int,
) -> int:
    """Insert or update a YouTube digest for a given date. Returns digest id."""
    cur = conn.execute(
        """INSERT INTO youtube_digests (date, title, summary_text, video_count, channel_count)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(date) DO UPDATE SET
               title = excluded.title,
               summary_text = excluded.summary_text,
               video_count = excluded.video_count,
               channel_count = excluded.channel_count,
               status = 'generated',
               updated_at = CURRENT_TIMESTAMP""",
        (date_str, title, summary_text, video_count, channel_count),
    )
    if cur.lastrowid:
        return cur.lastrowid
    row = conn.execute(
        "SELECT id FROM youtube_digests WHERE date = ?", (date_str,)
    ).fetchone()
    return row[0] if row else 0


def get_youtube_digest_for_date(
    conn: sqlite3.Connection, date_str: str
) -> dict[str, Any] | None:
    """Return the YouTube digest for a given date, or None."""
    row = conn.execute(
        "SELECT * FROM youtube_digests WHERE date = ?", (date_str,)
    ).fetchone()
    return dict(row) if row else None


def get_all_youtube_digests(
    conn: sqlite3.Connection, year: int | None = None, month: int | None = None
) -> list[dict[str, Any]]:
    """List YouTube digests, optionally filtered by year and/or month."""
    query = "SELECT * FROM youtube_digests"
    params = []
    conditions = []

    if year:
        conditions.append("strftime('%Y', date) = ?")
        params.append(str(year))
    if month and month > 0:
        conditions.append("strftime('%m', date) = ?")
        params.append(f"{int(month):02d}")

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY date DESC"

    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def link_videos_to_youtube_digest(
    conn: sqlite3.Connection, digest_id: int, article_ids: list[int]
) -> None:
    """Link YouTube videos to a digest. Deletes old links first."""
    conn.execute(
        "DELETE FROM youtube_digest_videos WHERE digest_id = ?", (digest_id,)
    )
    for i, aid in enumerate(article_ids):
        conn.execute(
            "INSERT INTO youtube_digest_videos (digest_id, article_id, inclusion_order)"
            " VALUES (?, ?, ?)",
            (digest_id, aid, i + 1),
        )


def get_youtube_digest_videos(
    conn: sqlite3.Connection, digest_id: int
) -> list[dict[str, Any]]:
    """Return videos linked to a YouTube digest, ordered by inclusion."""
    rows = conn.execute(
        """SELECT a.*, s.name as source_name, s.category as source_category,
                  ydv.inclusion_order
           FROM youtube_digest_videos ydv
           JOIN articles a ON ydv.article_id = a.id
           JOIN sources s ON a.source_id = s.id
           WHERE ydv.digest_id = ?
           ORDER BY ydv.inclusion_order""",
        (digest_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_youtube_channel_counts_for_date(
    conn: sqlite3.Connection, date_str: str
) -> dict[int, int]:
    """Return {source_id: video_count} for a given date.

    Used to display count badges in the channel list sidebar.
    """
    rows = conn.execute(
        """SELECT a.source_id, COUNT(*) as cnt
           FROM articles a
           JOIN sources s ON a.source_id = s.id
           WHERE s.category = 'youtube'
             AND a.status = 'summarized'
             AND date(a.fetched_at) = ?
           GROUP BY a.source_id""",
        (date_str,),
    ).fetchall()
    return {r["source_id"]: r["cnt"] for r in rows}


def get_recent_youtube_articles_for_channel(
    conn: sqlite3.Connection, source_id: int, days: int = 7
) -> list[dict[str, Any]]:
    """Get recent YouTube articles for a channel, used when channel hasn't posted today."""
    rows = conn.execute(
        """SELECT a.*, s.name as source_name
           FROM articles a
           JOIN sources s ON a.source_id = s.id
           WHERE a.source_id = ?
             AND s.category = 'youtube'
             AND a.status = 'summarized'
             AND a.fetched_at >= datetime('now', ?)
           ORDER BY a.published_at DESC
           LIMIT 20""",
        (source_id, f"-{days} days"),
    ).fetchall()
    return [dict(r) for r in rows]


def get_youtube_digest_years(conn: sqlite3.Connection) -> list[int]:
    """Return distinct years that have YouTube digests."""
    rows = conn.execute(
        "SELECT DISTINCT strftime('%Y', date) as year FROM youtube_digests ORDER BY year DESC"
    ).fetchall()
    return [int(r["year"]) for r in rows]


def get_recent_youtube_articles(
    conn: sqlite3.Connection, limit: int = 20, days: int = 7
) -> list[dict[str, Any]]:
    """Get recent YouTube articles across all channels."""
    rows = conn.execute(
        """SELECT a.*, s.name as source_name
           FROM articles a
           JOIN sources s ON a.source_id = s.id
           WHERE s.category = 'youtube'
             AND a.status = 'summarized'
             AND a.fetched_at >= datetime('now', ?)
           ORDER BY a.published_at DESC
           LIMIT ?""",
        (f"-{days} days", limit),
    ).fetchall()
    return [dict(r) for r in rows]