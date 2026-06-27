def _source(conn, name, url, source_type="rss", active=1):
    cursor = conn.execute(
        """INSERT INTO sources(name, feed_url, source_type, is_active)
           VALUES (?, ?, ?, ?)""", (name, url, source_type, active),
    )
    conn.commit()
    return cursor.lastrowid


def test_manual_selection_is_snapshotted_without_changing_active_state(isolated_db):
    conn = isolated_db.get_db()
    try:
        inactive = _source(conn, "Inactive", "inactive-feed", active=0)
        run_id = isolated_db.create_run(conn, "manual", [inactive], "2026-06-01", "2026-06-02")
        assert conn.execute("SELECT is_active FROM sources WHERE id=?", (inactive,)).fetchone()[0] == 0
        snapshot = conn.execute("SELECT source_name FROM run_sources WHERE run_id=?", (run_id,)).fetchone()
        assert snapshot[0] == "Inactive"
    finally:
        conn.close()


def test_scheduled_run_uses_only_active_unarchived_sources(isolated_db):
    conn = isolated_db.get_db()
    try:
        active = _source(conn, "Active", "active-feed")
        inactive = _source(conn, "Inactive", "inactive-feed", active=0)
        archived = _source(conn, "Archived", "archived-feed")
        conn.execute("UPDATE sources SET archived_at=CURRENT_TIMESTAMP WHERE id=?", (archived,)); conn.commit()
        run_id = isolated_db.create_run(conn, "scheduled")
        selected = {row[0] for row in conn.execute("SELECT source_id FROM run_sources WHERE run_id=?", (run_id,))}
        assert selected == {active}
        assert inactive not in selected
    finally:
        conn.close()


def test_archive_preserves_articles(isolated_db):
    conn = isolated_db.get_db()
    try:
        source_id = _source(conn, "Source", "feed")
        conn.execute("INSERT INTO articles(source_id,url,title) VALUES (?,?,?)", (source_id,"article","Title")); conn.commit()
        assert isolated_db.delete_source(conn, source_id) == 1
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 1
        assert conn.execute("SELECT archived_at FROM sources WHERE id=?", (source_id,)).fetchone()[0]
    finally:
        conn.close()


def test_publication_date_is_normalized_to_ist(isolated_db):
    conn = isolated_db.get_db()
    try:
        source_id = _source(conn, "Source", "feed")
        article_id = isolated_db.insert_article(
            conn, source_id=source_id, url="article", title="Title",
            published_at="2026-06-26T20:00:00+00:00",
        )
        conn.commit()
        assert conn.execute("SELECT published_date_ist FROM articles WHERE id=?", (article_id,)).fetchone()[0] == "2026-06-27"
    finally:
        conn.close()
