# Digest Read/Unread Tracking — Design

Date: 2026-08-09
Status: Approved (brainstorming)
Scope: A read/unread tracker for daily digests (RSS + YouTube) on the personal
news aggregator.

## 1. Problem

The user is busy and may skip reading a digest for several days. When they
return, there's no way to tell which digests (RSS or YouTube) they already read
versus missed, nor which were regenerated after being read. They need a
tracking system with a table of digest dates, read status per type, and links to
jump straight to a digest.

## 2. Requirements (agreed)

- Track read/unread **separately** for the RSS digest and the YouTube digest on
  the same date.
- **Unread when**: (a) digest is generated for the first time; (b) digest is
  regenerated (any regeneration resets to unread, per user's choice); (c) user
  manually marks it unread — stays unread until a read rule fires.
- **Read when**: (a) user scrolls to the bottom of the digest content card;
  (b) user manually marks it read (toggle button on the digest page, or
  checkbox in the tracker table).
- Tracker surfaced as a **new sidebar link + dedicated `/tracker` page**.
- Tracker table shows the **last 30 days**, newest first, one row per date with
  RSS + YouTube checkboxes and links.
- Both the digest-page toggle **and** the tracker checkboxes are interactive
  (both write the same flag).
- **No auth** on read-flag changes (matching the public digest pages).
- Existing digests (69 RSS + 26 YouTube) are **backfilled as read** when this
  ships.

## 3. Approach (chosen: A)

Add a `read_flag` column directly to each digest table. Digest generation and
regeneration already flow through `insert_daily_digest` /
`insert_youtube_digest` (both use `ON CONFLICT(date) DO UPDATE`), so resetting
the flag to 0 on every write covers "first generation → unread" and "any regen
→ unread" with a single change. One flag per digest row, no extra table, no
joins.

Rejected alternatives:
- **Separate tracker table** (`digest_reads(date, digest_type, read_flag)`):
  normalized but more code/joins for no current benefit.
- **Client-side only** (localStorage): state is per-browser, can't be driven by
  backend regen logic, and would differ across the user's devices. Not viable.

## 4. Data Model

- `daily_digests.read_flag INTEGER DEFAULT 0` (0 = unread, 1 = read)
- `youtube_digests.read_flag INTEGER DEFAULT 0`

Changes in `app/database.py`:
- Add `read_flag INTEGER DEFAULT 0` to both `CREATE TABLE` statements in
  `SCHEMA` so fresh databases get the column.
- `insert_daily_digest()`: add `read_flag = 0` to the
  `ON CONFLICT(date) DO UPDATE SET` clause.
- `insert_youtube_digest()`: same.
- New helper:
  ```python
  def set_digest_read_flag(conn, digest_type, date_str, read) -> bool
  ```
  Updates the flag for the given date in the given table. Returns False if no
  digest exists for that date (so the API can return 404), True otherwise.
- New helper:
  ```python
  def get_tracker_rows(conn, days=30) -> list[dict]
  ```
  Returns rows for dates that have at least one RSS or YouTube digest within
  the last `days`, newest first. Each row:
  ```python
  {
      "date": "2026-08-08",
      "rss_read": True | False | None,   # None = no RSS digest that day
      "youtube_read": True | False | None,
  }
  ```

Migration: `migrations/009_digest_read_flags.sql`
```sql
ALTER TABLE daily_digests ADD COLUMN read_flag INTEGER DEFAULT 0;
UPDATE daily_digests SET read_flag = 1;
ALTER TABLE youtube_digests ADD COLUMN read_flag INTEGER DEFAULT 0;
UPDATE youtube_digests SET read_flag = 1;
```
(SQLite supports `ADD COLUMN` with a default; the backfill `UPDATE`s existing
digests to read. New writes are forced to 0 by the `DO UPDATE SET` clause.)

Note: migrations are applied by `_run_migrations` (runs any unapplied
`*.sql` file in `migrations/`, ordered). `009` continues the existing
numbering (001, 002, 008).

## 5. Backend Routes (`app/web/routes.py`)

1. `GET /tracker` — renders `tracker.html` with `rows = get_tracker_rows(conn, days=30)`.
   - `rss_link = /digest/{date}` when an RSS digest exists, else None.
   - `youtube_link = /youtube?date={date}` when a YouTube digest exists, else None.
2. `POST /api/read` — JSON body `{"type": "rss"|"youtube", "date": "YYYY-MM-DD", "read": true|false}`.
   - Validates `type` and `date`; 400 on invalid input.
   - Calls `set_digest_read_flag`; 404 if no digest for that date.
   - Returns `{"ok": true}`.
   - No auth (consistent with public digest pages).
3. Sidebar link to `/tracker` added to `base.html` (desktop sidebar + mobile
   drawer), matching existing sidebar section styling. Icon suggestion: 📖.

## 6. Frontend

### 6.1 Tracker table (`app/web/templates/tracker.html`)

New template extending `base.html`. Table columns:

| Digest Date | RSS Read | YouTube Read | RSS Link | YouTube Link |

- **RSS Read / YouTube Read**: interactive checkboxes. Checked = read.
  - If the date has no digest of that type, the cell shows a dash (`—`).
  - Toggle → `POST /api/read` with `{type, date, read}`; on success update the
    checkbox state (and the digest-page marker state is naturally consistent
    next time that page loads).
- **RSS Link / YouTube Link**: links to `/digest/{date}` and
  `/youtube?date={date}`; dash when the digest doesn't exist.
- Rows are newest first (last 30 days).

### 6.2 Digest-page read/unread marker

Added to both `index.html` (RSS) and `youtube.html` (YouTube), near the date
navigation header:

- A small button showing the current state: "Mark as read" or "Mark as unread".
- Server passes the digest's `read_flag` into the template for initial state.
- Click → `POST /api/read` → flip the label.

### 6.3 Scroll auto-read

JS on both `index.html` and `youtube.html`:

- An `IntersectionObserver` watches the bottom edge (footer) of the digest
  content card.
- When the footer becomes visible **and** `window.scrollY > 0` (user actually
  scrolled), fire a single `POST /api/read` with `read: true`, then
  `observer.disconnect()`.
- Short digests that fit on screen without scrolling are NOT auto-marked
  (matches the "reach bottom of digest card" requirement).
- Failures are silent in JS; the manual toggle is the fallback.

## 7. Error Handling

- `/api/read`: 400 on bad type/date; 404 when the date has no digest of that
  type. JSON responses.
- Auto-read JS failures: silent (no alert); user can still use the manual toggle.
- Tracker page: empty state message when there are no digests in the window.

## 8. Testing

Follows the existing `isolated_db` fixture pattern in `tests/conftest.py`.

1. Migration: `init_db()` on a fresh DB leaves `read_flag` present in both
   tables; inserting then re-generating a digest resets `read_flag` to 0.
2. Regen reset: `insert_daily_digest` on an existing date resets `read_flag` to
   0 even if previously set to 1 (same for YouTube).
3. `set_digest_read_flag`: sets rss and youtube flags correctly; returns False
   for unknown date.
4. `get_tracker_rows`: returns last-30-days union, newest first, correct
   per-type flags, None for missing digest types.
5. `/api/read` endpoint: valid toggle updates the flag; invalid type → 400;
   unknown date → 404.
6. Template render: tracker.html renders checkboxes matching server state
   (via FastAPI TestClient or direct route test).

## 9. Files touched

- `app/database.py` — schema, two insert functions, two new helpers.
- `app/web/routes.py` — `/tracker`, `/api/read`, sidebar context.
- `app/web/templates/base.html` — sidebar link (desktop + mobile).
- `app/web/templates/tracker.html` — new page.
- `app/web/templates/index.html` — read/unread marker + auto-read JS.
- `app/web/templates/youtube.html` — read/unread marker + auto-read JS.
- `migrations/009_digest_read_flags.sql` — new migration.
- `tests/` — new tests for the above.

## 10. Out of scope (explicit)

- Per-article read tracking (only digest-level).
- Notifications/reminders for unread digests.
- Unread-count badges on the sidebar link.
- Anything beyond the last-30-day tracker window.
