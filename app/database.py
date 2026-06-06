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
        conn.commit()
    finally:
        conn.close()


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

CREATE INDEX IF NOT EXISTS idx_articles_status ON articles(status);
CREATE INDEX IF NOT EXISTS idx_articles_source_id ON articles(source_id);
CREATE INDEX IF NOT EXISTS idx_articles_fetched_at ON articles(fetched_at);
CREATE INDEX IF NOT EXISTS idx_daily_digests_date ON daily_digests(date);
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


# ---------------------------------------------------------------------------
# Articles CRUD
# ---------------------------------------------------------------------------


def insert_article(conn: sqlite3.Connection, **kwargs) -> int | None:
    """Insert an article. Returns its id, or None if URL already exists."""
    try:
        cur = conn.execute(
            """INSERT INTO articles
               (source_id, url, title, snippet, raw_text, author, published_at, fetched_at, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
    """Get all summarized articles fetched on a given date (IST day)."""
    rows = conn.execute(
        """SELECT a.*, s.name as source_name, s.category as source_category
           FROM articles a
           JOIN sources s ON a.source_id = s.id
           WHERE a.status = 'summarized'
             AND date(a.fetched_at) = date(?)
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
    return cur.lastrowid


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
    if month:
        conditions.append("strftime('%m', date) = ?")
        params.append(f"{month:02d}")

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
        """SELECT a.*, s.name as source_name
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
