import sqlite3
from pathlib import Path


def test_versioned_migration_is_idempotent(isolated_db):
    isolated_db.init_db()
    conn = isolated_db.get_db()
    try:
        migrations_dir = Path(__file__).resolve().parents[1] / "migrations"
        expected = len(list(migrations_dir.glob("*.sql")))
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == expected
        source_columns = {row[1] for row in conn.execute("PRAGMA table_info(sources)")}
        assert {"source_type", "archived_at", "last_fetch_status"} <= source_columns
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='runs'").fetchone()
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='transcript_jobs'").fetchone()
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='backfill_state'").fetchone()
    finally:
        conn.close()


def test_existing_001_database_receives_backfill_state_002(isolated_db):
    conn = isolated_db.get_db()
    conn.execute("DROP TABLE backfill_state")
    conn.execute("DELETE FROM schema_migrations WHERE version='002_backfill_state'")
    conn.commit()
    conn.close()

    isolated_db.init_db()
    conn = isolated_db.get_db()
    try:
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='backfill_state'").fetchone()
        assert conn.execute(
            "SELECT 1 FROM schema_migrations WHERE version='002_backfill_state'"
        ).fetchone()
    finally:
        conn.close()


def test_legacy_youtube_source_and_publication_date_are_backfilled(tmp_path, monkeypatch):
    import app.database as database
    path = tmp_path / "legacy.db"
    monkeypatch.setattr(database, "DB_PATH", path)
    conn = sqlite3.connect(path)
    conn.executescript(database.SCHEMA)
    conn.execute("INSERT INTO sources(name, feed_url, category) VALUES ('Channel','feed','youtube')")
    conn.execute(
        """INSERT INTO articles(source_id,url,title,published_at,status)
           VALUES (1,'video','Video','2026-06-26T20:00:00+00:00','summarized')"""
    )
    conn.commit(); conn.close()
    database.init_db()
    conn = database.get_db()
    try:
        assert conn.execute("SELECT source_type FROM sources").fetchone()[0] == "youtube"
        assert conn.execute("SELECT published_date_ist FROM articles").fetchone()[0] == "2026-06-27"
    finally:
        conn.close()
