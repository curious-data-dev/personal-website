import app.summarizer.service as service
from app.database import insert_article, insert_youtube_digest


def test_youtube_only_run_does_not_process_or_regenerate_rss(isolated_db, monkeypatch):
    conn = isolated_db.get_db()
    rss = conn.execute(
        "INSERT INTO sources(name,feed_url,source_type) VALUES ('RSS','rss','rss')"
    ).lastrowid
    youtube = conn.execute(
        "INSERT INTO sources(name,feed_url,source_type) VALUES ('YT','yt','youtube')"
    ).lastrowid
    rss_article = insert_article(
        conn, source_id=rss, url="rss-item", title="RSS", raw_text="r" * 200,
        published_at="2026-06-27T01:00:00+00:00", status="raw",
    )
    yt_article = insert_article(
        conn, source_id=youtube, url="yt-item", title="YT", raw_text="y" * 200,
        published_at="2026-06-27T02:00:00+00:00", status="raw",
    )
    insert_youtube_digest(conn, "2026-06-27", "Existing", "Existing", 0, 0)
    conn.commit(); conn.close()

    generated = []
    monkeypatch.setattr(service, "_summarize_article", lambda text: ("summary", 1, "test"))
    monkeypatch.setattr(service, "_generate_daily_digest", lambda conn, date: generated.append(("rss", date)))
    monkeypatch.setattr(service, "_generate_youtube_daily_digest", lambda conn, date: generated.append(("youtube", date)))

    service.run_summarization(source_types={"youtube"})

    conn = isolated_db.get_db()
    try:
        assert conn.execute("SELECT status FROM articles WHERE id=?", (rss_article,)).fetchone()[0] == "raw"
        assert conn.execute("SELECT status FROM articles WHERE id=?", (yt_article,)).fetchone()[0] == "summarized"
        assert generated == [("youtube", "2026-06-27")]
    finally:
        conn.close()
