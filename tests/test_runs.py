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


def test_claim_run_is_exclusive(isolated_db):
    """A run can be claimed once; a second claimer (worker) must fail.

    This guards against the app thread and the worker executing the same run.
    """
    conn = isolated_db.get_db()
    try:
        _source(conn, "Active", "active-feed")
        run_id = isolated_db.create_run(conn, "scheduled")
        assert isolated_db.claim_run(conn, run_id, "app", 60) is True
        assert isolated_db.claim_run(conn, run_id, "worker", 60) is False
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


def test_enqueue_scheduled_run_is_queued(isolated_db):
    """The scheduler must only enqueue; the worker owns execution."""
    from app.orchestration import enqueue_scheduled_run

    conn = isolated_db.get_db()
    try:
        _source(conn, "Active", "active-feed")
        run_id = enqueue_scheduled_run(conn)
        run = conn.execute(
            "SELECT status, trigger_type FROM runs WHERE id=?", (run_id,)
        ).fetchone()
        assert run["status"] == "queued"
        assert run["trigger_type"] == "scheduled"
        assert conn.execute(
            "SELECT count(*) FROM run_sources WHERE run_id=?", (run_id,)
        ).fetchone()[0] == 1
    finally:
        conn.close()


def test_execute_run_sends_kindle_after_summarization(isolated_db, monkeypatch):
    """Kindle delivery happens in the worker, after digests are regenerated."""
    import app.orchestration as orchestration
    from app.kindle import service as kindle_service

    conn = isolated_db.get_db()
    try:
        _source(conn, "Active", "active-feed")
        run_id = isolated_db.create_run(conn, "scheduled")
        run = isolated_db.get_run(conn, run_id)
    finally:
        conn.close()

    monkeypatch.setattr(
        orchestration, "run_scrape",
        lambda *a, **k: {"articles_new": 0, "errors": []},
    )
    monkeypatch.setattr(
        orchestration, "run_youtube_scrape",
        lambda *a, **k: {"videos_new": 0, "errors": []},
    )
    monkeypatch.setattr(
        orchestration, "process_pending_transcripts",
        lambda *a, **k: {},
    )
    monkeypatch.setattr(
        orchestration, "run_summarization",
        lambda *a, **k: {
            "articles_processed": 0,
            "digests_regenerated": {"rss": ["2026-10-18"], "youtube": []},
        },
    )

    calls = {}

    def fake_kindle(*, regenerated=None):
        calls["regenerated"] = regenerated
        return {"enabled": True, "results": []}

    monkeypatch.setattr(kindle_service, "send_digests_to_kindle", fake_kindle)

    orchestration.execute_run(run)

    assert calls["regenerated"] == {"rss": ["2026-10-18"], "youtube": []}
    conn = isolated_db.get_db()
    try:
        assert conn.execute(
            "SELECT status FROM runs WHERE id=?", (run_id,)
        ).fetchone()[0] == "no_new_content"
    finally:
        conn.close()


def test_execute_run_releases_db_lock_before_kindle(isolated_db, monkeypatch):
    """Regression: the Kindle phase must be able to write kindle_sends.

    The affected-dates connection used to keep an uncommitted write
    transaction open across the (slow) Kindle phase, so recording a send
    failed with "database is locked" and aborted the remaining candidates.
    """
    import app.orchestration as orchestration
    from app.kindle import service as kindle_service

    conn = isolated_db.get_db()
    try:
        source_id = _source(conn, "Active", "active-feed")
        run_id = isolated_db.create_run(conn, "scheduled")
        run = isolated_db.get_run(conn, run_id)
        article_id = isolated_db.insert_article(
            conn,
            source_id=source_id,
            url="article-1",
            title="Title",
            published_at="2026-10-18T05:00:00+00:00",
        )
        conn.execute(
            """UPDATE articles SET status='summarized',
                   published_date_ist='2026-10-18' WHERE id=?""",
            (article_id,),
        )
        conn.execute(
            "INSERT INTO run_items(run_id, article_id) VALUES (?, ?)",
            (run_id, article_id),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(
        orchestration, "run_scrape",
        lambda *a, **k: {"articles_new": 0, "errors": []},
    )
    monkeypatch.setattr(
        orchestration, "run_youtube_scrape",
        lambda *a, **k: {"videos_new": 0, "errors": []},
    )
    monkeypatch.setattr(
        orchestration, "process_pending_transcripts",
        lambda *a, **k: {},
    )
    monkeypatch.setattr(
        orchestration, "run_summarization",
        lambda *a, **k: {
            "articles_processed": 0,
            "digests_regenerated": {"rss": [], "youtube": []},
        },
    )

    outcome = {}

    def fake_kindle(*, regenerated=None):
        # Separate connection, exactly like the real Kindle service.
        kc = isolated_db.get_db()
        try:
            kc.execute("PRAGMA busy_timeout=200")
            kc.execute(
                """INSERT OR REPLACE INTO kindle_sends
                   (digest_type, digest_date, content_hash)
                   VALUES ('rss', '2026-10-18', 'test')"""
            )
            kc.commit()
            outcome["ok"] = True
        except Exception as e:  # pragma: no cover - only on the regression
            outcome["error"] = repr(e)
        finally:
            kc.close()
        return {"enabled": True, "results": []}

    monkeypatch.setattr(kindle_service, "send_digests_to_kindle", fake_kindle)

    orchestration.execute_run(run)

    assert outcome.get("ok") is True, outcome
