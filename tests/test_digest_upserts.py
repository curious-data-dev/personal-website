from app.database import insert_daily_digest, insert_youtube_digest, link_articles_to_digest, link_videos_to_youtube_digest


def _article(conn, suffix):
    source = conn.execute(
        "INSERT INTO sources(name,feed_url,source_type) VALUES (?,?,?)",
        (f"Source {suffix}", f"feed-{suffix}", "rss"),
    ).lastrowid
    return conn.execute(
        "INSERT INTO articles(source_id,url,title) VALUES (?,?,?)",
        (source, f"url-{suffix}", f"Title {suffix}"),
    ).lastrowid


def test_rss_digest_update_returns_existing_digest_id(isolated_db):
    conn = isolated_db.get_db()
    try:
        first = insert_daily_digest(conn, "2026-06-27", "First", "One", 1, 1)
        article = _article(conn, "rss")
        updated = insert_daily_digest(conn, "2026-06-27", "Updated", "Two", 1, 1)
        assert updated == first
        link_articles_to_digest(conn, updated, [article])
        conn.commit()
    finally:
        conn.close()


def test_youtube_digest_update_returns_existing_digest_id(isolated_db):
    conn = isolated_db.get_db()
    try:
        first = insert_youtube_digest(conn, "2026-06-27", "First", "One", 1, 1)
        article = _article(conn, "youtube")
        updated = insert_youtube_digest(conn, "2026-06-27", "Updated", "Two", 1, 1)
        assert updated == first
        link_videos_to_youtube_digest(conn, updated, [article])
        conn.commit()
    finally:
        conn.close()
