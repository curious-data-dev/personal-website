from datetime import datetime, timezone, timedelta

from app.database import insert_daily_digest, insert_youtube_digest, set_digest_read_flag, get_tracker_rows


def ist_date(days_ago: int) -> str:
    ist = timezone(timedelta(hours=5, minutes=30))
    today = datetime.now(ist).date()
    return (today - timedelta(days=days_ago)).isoformat()


def test_set_read_flag_rss_and_youtube(isolated_db):
    conn = isolated_db.get_db()
    try:
        insert_daily_digest(conn, ist_date(1), "R", "x", 1, 1)
        insert_youtube_digest(conn, ist_date(1), "Y", "x", 1, 1)
        assert set_digest_read_flag(conn, "rss", ist_date(1), True) is True
        assert set_digest_read_flag(conn, "youtube", ist_date(1), True) is True
        assert conn.execute("SELECT read_flag FROM daily_digests").fetchone()[0] == 1
        assert conn.execute("SELECT read_flag FROM youtube_digests").fetchone()[0] == 1
    finally:
        conn.close()


def test_set_read_flag_unknown_date_returns_false(isolated_db):
    conn = isolated_db.get_db()
    try:
        assert set_digest_read_flag(conn, "rss", "2026-01-01", True) is False
        assert set_digest_read_flag(conn, "youtube", "2026-01-01", True) is False
    finally:
        conn.close()


def test_tracker_rows_union_and_ordering(isolated_db):
    conn = isolated_db.get_db()
    try:
        insert_daily_digest(conn, ist_date(2), "R2", "x", 1, 1)
        insert_youtube_digest(conn, ist_date(2), "Y2", "x", 1, 1)
        insert_daily_digest(conn, ist_date(1), "R1", "x", 1, 1)  # rss only
        set_digest_read_flag(conn, "rss", ist_date(2), True)

        rows = get_tracker_rows(conn, days=30)
        assert [r["date"] for r in rows] == [ist_date(1), ist_date(2)]

        by_date = {r["date"]: r for r in rows}
        assert by_date[ist_date(2)]["rss_read"] is True
        assert by_date[ist_date(2)]["youtube_read"] is False
        assert by_date[ist_date(1)]["rss_read"] is False
        assert by_date[ist_date(1)]["youtube_read"] is None
    finally:
        conn.close()


def test_tracker_rows_excludes_dates_outside_window(isolated_db):
    conn = isolated_db.get_db()
    try:
        insert_daily_digest(conn, ist_date(1), "In", "x", 1, 1)
        insert_daily_digest(conn, ist_date(60), "Out", "x", 1, 1)
        rows = get_tracker_rows(conn, days=30)
        assert [r["date"] for r in rows] == [ist_date(1)]
    finally:
        conn.close()
