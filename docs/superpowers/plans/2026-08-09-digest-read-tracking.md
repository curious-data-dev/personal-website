# Digest Read/Unread Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Track read/unread state for RSS and YouTube daily digests — with a tracker page, manual toggles, auto-unread on regeneration, and auto-read when the user scrolls to the bottom of a digest.

**Architecture:** Add a `read_flag INTEGER` column to `daily_digests` and `youtube_digests` via a versioned migration. Digest generation/regeneration already flows through `insert_daily_digest` / `insert_youtube_digest` (both use `ON CONFLICT(date) DO UPDATE`), so forcing `read_flag = 0` in that update clause makes "first generation → unread" and "any regen → unread" fall out of one change. New helpers (`set_digest_read_flag`, `get_tracker_rows`) back the new `/tracker` page and `POST /api/read` endpoint. Client JS on the digest pages fires the auto-read via `IntersectionObserver` + scroll check.

**Tech Stack:** Python, FastAPI, Jinja2 (Tailwind), SQLite (raw sqlite3), pytest with `isolated_db` fixture. No new dependencies.

## Global Constraints

- Read state is tracked **separately** per digest type (`rss` / `youtube`) even for the same date.
- `read_flag`: 0 = unread, 1 = read. New digests and any regeneration → 0.
- Existing digests backfilled as **read** (1) by the migration.
- **Do NOT** add `read_flag` to `SCHEMA`'s `CREATE TABLE` statements — only the migration adds the column (fresh DBs run the migration too; SCHEMA + migration would duplicate the column and crash). See `migrations/001` for the established pattern.
- `/api/read` and the tracker page require **no auth**.
- Tests MUST run on Windows with a custom basetemp:
  `.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider --basetemp "C:\Users\pc\AppData\Local\Temp\opencode\pytest-basetmp"`
- Follow existing code style: no new dependencies, raw sqlite3, `sqlite3.Row` dicts.

---

### Task 1: Migration + insert-function read_flag reset

**Files:**
- Create: `migrations/009_digest_read_flags.sql`
- Modify: `app/database.py:457-481` (`insert_daily_digest`), `app/database.py:708-732` (`insert_youtube_digest`)
- Test: `tests/test_digest_upserts.py` (add tests)

**Interfaces:**
- Consumes: nothing new.
- Produces: `read_flag` column on both digest tables; the guarantee that every call to `insert_daily_digest` / `insert_youtube_digest` leaves `read_flag = 0` on the stored row.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_digest_upserts.py`:

```python
def _read_flag(conn, table, date_str):
    return conn.execute(
        f"SELECT read_flag FROM {table} WHERE date = ?", (date_str,)
    ).fetchone()[0]


def test_rss_regen_resets_read_flag(isolated_db):
    conn = isolated_db.get_db()
    try:
        insert_daily_digest(conn, "2026-06-27", "First", "One", 1, 1)
        conn.execute("UPDATE daily_digests SET read_flag = 1 WHERE date = '2026-06-27'")
        conn.commit()
        insert_daily_digest(conn, "2026-06-27", "Regen", "Two", 2, 2)
        assert _read_flag(conn, "daily_digests", "2026-06-27") == 0
    finally:
        conn.close()


def test_youtube_regen_resets_read_flag(isolated_db):
    conn = isolated_db.get_db()
    try:
        insert_youtube_digest(conn, "2026-06-27", "First", "One", 1, 1)
        conn.execute("UPDATE youtube_digests SET read_flag = 1 WHERE date = '2026-06-27'")
        conn.commit()
        insert_youtube_digest(conn, "2026-06-27", "Regen", "Two", 2, 2)
        assert _read_flag(conn, "youtube_digests", "2026-06-27") == 0
    finally:
        conn.close()


def test_fresh_insert_read_flag_defaults_unread(isolated_db):
    conn = isolated_db.get_db()
    try:
        insert_daily_digest(conn, "2026-06-28", "First", "One", 1, 1)
        assert _read_flag(conn, "daily_digests", "2026-06-28") == 0
    finally:
        conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_digest_upserts.py -q -p no:cacheprovider --basetemp "C:\Users\pc\AppData\Local\Temp\opencode\pytest-basetmp"`
Expected: FAIL — `no such column: read_flag` (column doesn't exist yet).

- [ ] **Step 3: Create the migration**

Create `migrations/009_digest_read_flags.sql`:

```sql
ALTER TABLE daily_digests ADD COLUMN read_flag INTEGER DEFAULT 0;
UPDATE daily_digests SET read_flag = 1;
ALTER TABLE youtube_digests ADD COLUMN read_flag INTEGER DEFAULT 0;
UPDATE youtube_digests SET read_flag = 1;
```

The `ALTER ... DEFAULT 0` makes fresh inserts default to unread; the backfill `UPDATE`s set existing rows to read.

- [ ] **Step 4: Add `read_flag = 0` to both insert functions**

In `app/database.py`, `insert_daily_digest` — add `read_flag = 0,` to the `ON CONFLICT(date) DO UPDATE SET` clause (after `status = 'generated',`):

```python
    conn.execute(
        """INSERT INTO daily_digests (date, title, summary_text, article_count, source_count)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(date) DO UPDATE SET
               title = excluded.title,
               summary_text = excluded.summary_text,
               article_count = excluded.article_count,
               source_count = excluded.source_count,
               status = 'generated',
               read_flag = 0,
               updated_at = CURRENT_TIMESTAMP""",
        ...
```

In `app/database.py`, `insert_youtube_digest` — same addition to its `ON CONFLICT(date) DO UPDATE SET` clause:

```python
    conn.execute(
        """INSERT INTO youtube_digests (date, title, summary_text, video_count, channel_count)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(date) DO UPDATE SET
               title = excluded.title,
               summary_text = excluded.summary_text,
               video_count = excluded.video_count,
               channel_count = excluded.channel_count,
               status = 'generated',
               read_flag = 0,
               updated_at = CURRENT_TIMESTAMP""",
        ...
```

Note: on a brand-new INSERT the `DEFAULT 0` already yields unread; the explicit `read_flag = 0` in the UPDATE clause is what resets it on regeneration. Do NOT touch `SCHEMA`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_digest_upserts.py -q -p no:cacheprovider --basetemp "C:\Users\pc\AppData\Local\Temp\opencode\pytest-basetmp"`
Expected: PASS (all 5 tests in the file).

- [ ] **Step 6: Run the full suite**

Run: `pytest tests -q -p no:cacheprovider --basetemp "C:\Users\pc\AppData\Local\Temp\opencode\pytest-basetmp"`
Expected: all pass. `test_versioned_migration_is_idempotent` counts migrations from the directory, so it auto-includes 009.

- [ ] **Step 7: Commit**

```bash
git add migrations/009_digest_read_flags.sql app/database.py tests/test_digest_upserts.py
git commit -m "feat: add read_flag to digests, reset to unread on generation/regen"
```

---

### Task 2: DB helpers `set_digest_read_flag` + `get_tracker_rows`

**Files:**
- Modify: `app/database.py` (append helpers in the Daily Digests CRUD section, ~after `get_digest_years`)
- Test: `tests/test_tracker_helpers.py` (create)

**Interfaces:**
- Consumes: `read_flag` column from Task 1.
- Produces:
  ```python
  def set_digest_read_flag(conn, digest_type: str, date_str: str, read: bool) -> bool
  #   digest_type in {"rss", "youtube"}; returns True if a row was updated, False if no digest for that date.

  def get_tracker_rows(conn, days: int = 30) -> list[dict]
  #   Each dict: {"date": "YYYY-MM-DD", "rss_read": bool|None, "youtube_read": bool|None}
  #   Dates that have at least one digest type in the last `days` days, newest first.
  ```

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tracker_helpers.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_tracker_helpers.py -q -p no:cacheprovider --basetemp "C:\Users\pc\AppData\Local\Temp\opencode\pytest-basetmp"`
Expected: FAIL — `ImportError` / `AttributeError` (helpers don't exist yet).

- [ ] **Step 3: Implement `set_digest_read_flag`**

Append to `app/database.py` (after `get_digest_years`):

```python
def set_digest_read_flag(
    conn: sqlite3.Connection, digest_type: str, date_str: str, read: bool
) -> bool:
    """Set the read/unread flag for a digest. Returns False if no digest exists."""
    table = "daily_digests" if digest_type == "rss" else "youtube_digests"
    cur = conn.execute(
        f"UPDATE {table} SET read_flag = ? WHERE date = ?",
        (1 if read else 0, date_str),
    )
    return cur.rowcount > 0
```

- [ ] **Step 4: Implement `get_tracker_rows`**

Append to `app/database.py` (after `set_digest_read_flag`):

```python
def get_tracker_rows(
    conn: sqlite3.Connection, days: int = 30
) -> list[dict[str, Any]]:
    """Return read-flag rows for dates with an RSS or YouTube digest in the
    last `days` days, newest first. Missing digest types are None."""
    ist = timezone(timedelta(hours=5, minutes=30))
    cutoff = (datetime.now(ist).date() - timedelta(days=days - 1)).isoformat()
    rows = conn.execute(
        """SELECT 'rss' AS type, date, read_flag FROM daily_digests
           WHERE date >= ?
           UNION ALL
           SELECT 'youtube' AS type, date, read_flag FROM youtube_digests
           WHERE date >= ?""",
        (cutoff, cutoff),
    ).fetchall()

    by_date: dict[str, dict[str, Any]] = {}
    for r in rows:
        entry = by_date.setdefault(
            r["date"], {"date": r["date"], "rss_read": None, "youtube_read": None}
        )
        entry[f"{r['type']}_read"] = bool(r["read_flag"])
    return sorted(by_date.values(), key=lambda e: e["date"], reverse=True)
```

`timezone`, `timedelta`, and `datetime` are already imported at the top of `app/database.py`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_tracker_helpers.py -q -p no:cacheprovider --basetemp "C:\Users\pc\AppData\Local\Temp\opencode\pytest-basetmp"`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add app/database.py tests/test_tracker_helpers.py
git commit -m "feat: add digest read-flag and tracker-row DB helpers"
```

---

### Task 3: `/api/read` endpoint + `/tracker` route

**Files:**
- Modify: `app/web/routes.py` (imports, two new routes)
- Test: `tests/test_read_tracker_routes.py` (create)

**Interfaces:**
- Consumes: `set_digest_read_flag`, `get_tracker_rows` from Task 2.
- Produces:
  - `POST /api/read` — body `{"type": "rss"|"youtube", "date": "YYYY-MM-DD", "read": bool}`; 200 `{"ok": true}`; 400 bad type/date; 404 no digest.
  - `GET /tracker` — renders `tracker.html` (Task 4) with `rows` where each row additionally carries `rss_link` / `youtube_link`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_read_tracker_routes.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_read_tracker_routes.py -q -p no:cacheprovider --basetemp "C:\Users\pc\AppData\Local\Temp\opencode\pytest-basetmp"`
Expected: FAIL — 404 (routes don't exist yet).

- [ ] **Step 3: Implement `/api/read`**

In `app/web/routes.py`, add `set_digest_read_flag` to the imports from `app.database` (the import block at lines 16-49), then add after the `history` route (near line 428):

```python
@router.post("/api/read")
async def api_set_read(request: Request):
    """Set a digest's read/unread flag. No auth (matches public digest pages)."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    digest_type = (body.get("type") or "").strip().lower()
    date_str = (body.get("date") or "").strip()
    read = bool(body.get("read"))

    if digest_type not in {"rss", "youtube"}:
        raise HTTPException(status_code=400, detail="type must be 'rss' or 'youtube'")
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")

    conn = get_db()
    try:
        updated = set_digest_read_flag(conn, digest_type, date_str, read)
        if not updated:
            raise HTTPException(status_code=404, detail="No digest for this date")
        conn.commit()
        return JSONResponse({"ok": True})
    finally:
        conn.close()
```

`datetime` is already imported in `routes.py`.

- [ ] **Step 4: Implement `/tracker`**

In `app/web/routes.py`, add `get_tracker_rows` to the `app.database` imports, then add below the `/api/read` route:

```python
@router.get("/tracker", response_class=HTMLResponse)
async def tracker(request: Request):
    """Read/unread tracker for RSS and YouTube digests (last 30 days)."""
    conn = get_db()
    try:
        rows = get_tracker_rows(conn, days=30)
        for r in rows:
            r["rss_link"] = f"/digest/{r['date']}" if r["rss_read"] is not None else None
            r["youtube_link"] = f"/youtube?date={r['date']}" if r["youtube_read"] is not None else None
        return templates.TemplateResponse(
            request,
            "tracker.html",
            {"rows": rows},
        )
    finally:
        conn.close()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_read_tracker_routes.py -q -p no:cacheprovider --basetemp "C:\Users\pc\AppData\Local\Temp\opencode\pytest-basetmp"`
Expected: `test_api_read_sets_flag`, `test_api_read_bad_type_returns_400`, `test_api_read_unknown_date_returns_404` PASS. `test_tracker_page_renders` FAILS — template `tracker.html` doesn't exist yet (Task 4). This is expected; the tracker template test will pass after Task 4.

- [ ] **Step 6: Commit**

```bash
git add app/web/routes.py tests/test_read_tracker_routes.py
git commit -m "feat: add /api/read endpoint and /tracker route"
```

---

### Task 4: Tracker template + sidebar link + digest-page read markers + auto-read JS

**Files:**
- Create: `app/web/templates/tracker.html`
- Modify: `app/web/templates/base.html` (sidebar, ~lines 48-71)
- Modify: `app/web/templates/index.html` (marker + auto-read JS)
- Modify: `app/web/templates/youtube.html` (marker + auto-read JS)
- Test: `tests/test_read_tracker_routes.py` (enable `test_tracker_page_renders`)

**Interfaces:**
- Consumes: `/tracker` route (Task 3) providing `rows` with `date`, `rss_read`, `youtube_read`, `rss_link`, `youtube_link`; digest pages with `digest.read_flag`.
- Produces: working tracker table + interactive checkboxes; read/unread toggle buttons on both digest pages; scroll-to-bottom auto-read.

- [ ] **Step 1: Create `tracker.html`**

Create `app/web/templates/tracker.html`:

```jinja
{% extends "base.html" %}
{% block title %}Reading Tracker{% endblock %}

{% block content %}
<h1 class="text-2xl font-bold text-gray-900 dark:text-white mb-1">📖 Reading Tracker</h1>
<p class="text-sm text-gray-500 dark:text-slate-400 mb-6">Last 30 days of digests. Check a box when you've read it.</p>

{% if rows %}
<div class="overflow-x-auto rounded-xl shadow-sm border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900">
    <table class="w-full text-sm">
        <thead>
            <tr class="border-b border-gray-100 dark:border-slate-800 text-left text-xs uppercase tracking-wider text-gray-400 dark:text-slate-500">
                <th class="px-4 py-3 font-semibold">Digest Date</th>
                <th class="px-4 py-3 font-semibold">RSS Read</th>
                <th class="px-4 py-3 font-semibold">YouTube Read</th>
                <th class="px-4 py-3 font-semibold">RSS Link</th>
                <th class="px-4 py-3 font-semibold">YouTube Link</th>
            </tr>
        </thead>
        <tbody>
        {% for r in rows %}
            <tr class="border-b border-gray-50 dark:border-slate-800/50">
                <td class="px-4 py-2.5 font-medium text-gray-900 dark:text-white">{{ r.date }}</td>
                <td class="px-4 py-2.5">
                    {% if r.rss_read is not none %}
                    <input type="checkbox" class="read-toggle w-4 h-4 cursor-pointer"
                           data-type="rss" data-date="{{ r.date }}" {% if r.rss_read %}checked{% endif %}>
                    {% else %}
                    <span class="text-gray-300 dark:text-slate-600">—</span>
                    {% endif %}
                </td>
                <td class="px-4 py-2.5">
                    {% if r.youtube_read is not none %}
                    <input type="checkbox" class="read-toggle w-4 h-4 cursor-pointer"
                           data-type="youtube" data-date="{{ r.date }}" {% if r.youtube_read %}checked{% endif %}>
                    {% else %}
                    <span class="text-gray-300 dark:text-slate-600">—</span>
                    {% endif %}
                </td>
                <td class="px-4 py-2.5">
                    {% if r.rss_link %}
                    <a href="{{ r.rss_link }}" class="text-blue-600 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300">Open</a>
                    {% else %}
                    <span class="text-gray-300 dark:text-slate-600">—</span>
                    {% endif %}
                </td>
                <td class="px-4 py-2.5">
                    {% if r.youtube_link %}
                    <a href="{{ r.youtube_link }}" class="text-blue-600 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300">Open</a>
                    {% else %}
                    <span class="text-gray-300 dark:text-slate-600">—</span>
                    {% endif %}
                </td>
            </tr>
        {% endfor %}
        </tbody>
    </table>
</div>

<script>
(function() {
    document.querySelectorAll('.read-toggle').forEach(function(cb) {
        cb.addEventListener('change', async function() {
            const body = {
                type: cb.dataset.type,
                date: cb.dataset.date,
                read: cb.checked
            };
            try {
                const resp = await fetch('/api/read', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });
                if (!resp.ok) cb.checked = !cb.checked;
            } catch (e) {
                cb.checked = !cb.checked;
            }
        });
    });
})();
</script>

{% else %}
<div class="flex flex-col items-center justify-center py-16 text-center">
    <div class="text-5xl mb-3">📖</div>
    <h3 class="text-lg font-semibold text-gray-900 dark:text-white mb-1">No digests in the last 30 days</h3>
    <p class="text-sm text-gray-500 dark:text-slate-400">Check back once the daily scrape runs.</p>
</div>
{% endif %}
{% endblock %}
```

- [ ] **Step 2: Add sidebar link in `base.html`**

In the desktop sidebar `<nav>` (after the History link, ~line 69), add:

```jinja
<a href="/tracker" class="sidebar-link {% if request.url.path.startswith('/tracker') %}sidebar-link-active{% endif %}">
    <span>📖</span><span class="sidebar-label">Tracker</span>
</a>
```

In the mobile drawer `<nav>` (after the History link, ~line 236), add:

```jinja
<a href="/tracker" class="sidebar-link {% if request.url.path.startswith('/tracker') %}sidebar-link-active{% endif %}">
    <span>📖</span><span>Tracker</span>
</a>
```

- [ ] **Step 3: Add read/unread marker + auto-read JS to `index.html`**

In the digest content block, add a toggle button above the `<article>` (right after the date-navigation `<div>` closes, i.e. after line 25). Insert this before the `{# ── Digest Content ── #}` block:

```jinja
{# ── Read/Unread marker ── #}
{% if digest %}
<div class="flex justify-end mb-4">
    <button id="digestReadToggle" data-type="rss" data-date="{{ today_str }}" data-read="{{ '1' if digest.read_flag else '0' }}"
            class="inline-flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-xs font-medium border transition-colors
            {% if digest.read_flag %}bg-green-50 dark:bg-green-950 text-green-700 dark:text-green-400 border-green-200 dark:border-green-800{% else %}bg-amber-50 dark:bg-amber-950 text-amber-700 dark:text-amber-400 border-amber-200 dark:border-amber-800{% endif %}">
        {% if digest.read_flag %}✓ Read{% else %}● Unread{% endif %}
    </button>
</div>
{% endif %}
```

Add `id="digest-end"` to the digest `<footer>` (line 61) so the observer has an anchor:

```jinja
    <footer id="digest-end" class="mt-6 pt-4 border-t ...">
```

Add this JS before the closing `{% endblock %}` (after line 118):

```jinja
<script>
(function() {
    // Read/unread marker toggle
    const toggle = document.getElementById('digestReadToggle');
    if (toggle) {
        toggle.addEventListener('click', async function() {
            const next = !(toggle.dataset.read === '1');
            try {
                const resp = await fetch('/api/read', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ type: toggle.dataset.type, date: toggle.dataset.date, read: next })
                });
                if (!resp.ok) return;
                toggle.dataset.read = next ? '1' : '0';
                toggle.classList.toggle('bg-green-50', next);
                toggle.classList.toggle('text-green-700', next);
                toggle.classList.toggle('border-green-200', next);
                toggle.classList.toggle('bg-amber-50', !next);
                toggle.classList.toggle('text-amber-700', !next);
                toggle.classList.toggle('border-amber-200', !next);
                toggle.textContent = next ? '✓ Read' : '● Unread';
            } catch (e) {}
        });
    }

    // Auto-read when the bottom of the digest card becomes visible after scrolling
    const end = document.getElementById('digest-end');
    if (end && toggle && toggle.dataset.read !== '1') {
        const observer = new IntersectionObserver(function(entries) {
            if (entries.some(function(e) { return e.isIntersecting && window.scrollY > 0; })) {
                fetch('/api/read', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ type: toggle.dataset.type, date: toggle.dataset.date, read: true })
                }).catch(function() {});
                observer.disconnect();
            }
        }, { rootMargin: '0px 0px 40px 0px' });
        observer.observe(end);
    }
})();
</script>
```

The `data-read` attribute on the button carries the server-side initial state (set in the template above), so the JS toggle and the auto-read guard (`toggle.dataset.read !== '1'`) both know whether the digest was already read.

- [ ] **Step 4: Add read/unread marker + auto-read JS to `youtube.html`**

In the "State 4: Digest exists" branch (line 200), add a toggle button immediately before the `<article>`:

```jinja
{% if digest %}
<div class="flex justify-end mb-4">
    <button id="youtubeReadToggle" data-type="youtube" data-date="{{ display_date }}" data-read="{{ '1' if digest.read_flag else '0' }}"
            class="inline-flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-xs font-medium border transition-colors
            {% if digest.read_flag %}bg-green-50 dark:bg-green-950 text-green-700 dark:text-green-400 border-green-200 dark:border-green-800{% else %}bg-amber-50 dark:bg-amber-950 text-amber-700 dark:text-amber-400 border-amber-200 dark:border-amber-800{% endif %}">
        {% if digest.read_flag %}✓ Read{% else %}● Unread{% endif %}
    </button>
</div>
{% endif %}
```

Add `id="digest-end"` to the digest `<footer>` (line 205).

Add this JS before the closing `{% endblock %}` (after the footnotes JS block, near line 275):

```jinja
<script>
(function() {
    const toggle = document.getElementById('youtubeReadToggle');
    if (toggle) {
        toggle.addEventListener('click', async function() {
            const next = !(toggle.dataset.read === '1');
            try {
                const resp = await fetch('/api/read', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ type: toggle.dataset.type, date: toggle.dataset.date, read: next })
                });
                if (!resp.ok) return;
                toggle.dataset.read = next ? '1' : '0';
                toggle.classList.toggle('bg-green-50', next);
                toggle.classList.toggle('text-green-700', next);
                toggle.classList.toggle('border-green-200', next);
                toggle.classList.toggle('bg-amber-50', !next);
                toggle.classList.toggle('text-amber-700', !next);
                toggle.classList.toggle('border-amber-200', !next);
                toggle.textContent = next ? '✓ Read' : '● Unread';
            } catch (e) {}
        });
    }

    const end = document.getElementById('digest-end');
    if (end && toggle && toggle.dataset.read !== '1') {
        const observer = new IntersectionObserver(function(entries) {
            if (entries.some(function(e) { return e.isIntersecting && window.scrollY > 0; })) {
                fetch('/api/read', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ type: toggle.dataset.type, date: toggle.dataset.date, read: true })
                }).catch(function() {});
                observer.disconnect();
            }
        }, { rootMargin: '0px 0px 40px 0px' });
        observer.observe(end);
    }
})();
</script>
```

Note: `display_date` is the digest's actual date in the route context, which is what the `/api/read` endpoint expects.

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_read_tracker_routes.py -q -p no:cacheprovider --basetemp "C:\Users\pc\AppData\Local\Temp\opencode\pytest-basetmp"`
Expected: all 4 tests PASS now (including `test_tracker_page_renders`).

- [ ] **Step 6: Manual verification**

Start the dev server:
```bash
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```
1. Visit `/tracker` — table shows the last 30 days; checkboxes toggle and persist across reload.
2. Visit `/digest/2026-08-08` — "Read"/"Unread" button reflects state; click toggles it.
3. Scroll to the bottom of a digest card → after reaching the footer, reload → shows "Read".
4. Short digest that fits on screen without scrolling → NOT auto-marked.
5. On the YouTube page, same marker + auto-read works.
6. Regenerate a digest (admin) → its flag resets to Unread.

- [ ] **Step 7: Run the full suite**

Run: `pytest tests -q -p no:cacheprovider --basetemp "C:\Users\pc\AppData\Local\Temp\opencode\pytest-basetmp"`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add app/web/templates/tracker.html app/web/templates/base.html app/web/templates/index.html app/web/templates/youtube.html tests/test_read_tracker_routes.py
git commit -m "feat: tracker page, sidebar link, digest read markers, scroll auto-read"
```

---

### Task 5: Update AGENTS.md + spec notes

**Files:**
- Modify: `AGENTS.md`
- Modify: `docs/superpowers/specs/2026-08-09-digest-read-tracking-design.md` (only if implementation diverged — record any decisions)

**Interfaces:**
- Consumes: everything above.
- Produces: project documentation consistent with the new feature.

- [ ] **Step 1: Update AGENTS.md**

Add a short "Read Tracking" section under `## 6. Known Problems & Fixes` (new `### 6.10`) documenting:
- `read_flag` column on `daily_digests` and `youtube_digests` (0 unread / 1 read).
- Migration `009_digest_read_flags.sql` backfills existing digests as read; NOT in SCHEMA (would duplicate column on fresh DBs).
- Every `insert_daily_digest` / `insert_youtube_digest` call resets `read_flag = 0` (covers first-generation AND regeneration).
- Routes: `GET /tracker`, `POST /api/read` (no auth).
- Auto-read rule: scroll to bottom of digest card + `scrollY > 0`; short digests aren't auto-marked.
- Tracker shows last 30 days; per-type flags.

- [ ] **Step 2: Final full-suite run**

Run: `pytest tests -q -p no:cacheprovider --basetemp "C:\Users\pc\AppData\Local\Temp\opencode\pytest-basetmp"`
Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add AGENTS.md
git commit -m "docs: document digest read/unread tracking in AGENTS.md"
```
