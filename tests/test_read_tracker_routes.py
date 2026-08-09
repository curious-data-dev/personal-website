import sqlite3
from datetime import datetime, timezone, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.web.routes import router
from app.database import insert_daily_digest, insert_youtube_digest


@pytest.fixture
def client(isolated_db):
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as c:
        yield c


def ist_date(days_ago: int) -> str:
    ist = timezone(timedelta(hours=5, minutes=30))
    today = datetime.now(ist).date()
    return (today - timedelta(days=days_ago)).isoformat()


def test_api_read_sets_flag(client, isolated_db):
    conn = isolated_db.get_db()
    try:
        insert_daily_digest(conn, ist_date(1), "R", "x", 1, 1)
        conn.commit()
    finally:
        conn.close()
    resp = client.post("/api/read", json={"type": "rss", "date": ist_date(1), "read": True})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    conn = isolated_db.get_db()
    try:
        assert conn.execute("SELECT read_flag FROM daily_digests").fetchone()[0] == 1
    finally:
        conn.close()


def test_api_read_bad_type_returns_400(client):
    resp = client.post("/api/read", json={"type": "tv", "date": "2026-01-01", "read": True})
    assert resp.status_code == 400


def test_api_read_unknown_date_returns_404(client):
    resp = client.post("/api/read", json={"type": "rss", "date": "2026-01-01", "read": True})
    assert resp.status_code == 404


def test_tracker_page_renders(client, isolated_db):
    conn = isolated_db.get_db()
    try:
        insert_daily_digest(conn, ist_date(1), "R", "x", 1, 1)
        insert_youtube_digest(conn, ist_date(1), "Y", "x", 1, 1)
        conn.commit()
    finally:
        conn.close()
    resp = client.get("/tracker")
    assert resp.status_code == 200
    html = resp.text
    assert ist_date(1) in html
    assert f"/digest/{ist_date(1)}" in html
    assert f"/youtube?date={ist_date(1)}" in html
