"""FastAPI route definitions for the web interface."""

import re
import secrets
import threading
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Request, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.database import (
    get_db,
    upsert_source,
    update_source,
    delete_source,
    update_source_active,
    get_articles_for_source,
    get_digest_for_date,
    get_all_digests,
    get_digest_years,
    get_digest_articles,
    get_article,
    get_all_sources,
    get_active_sources,
    get_recent_articles,
    get_last_scrape,
    get_adjacent_dates,
    get_youtube_sources,
    get_active_youtube_sources,
    upsert_youtube_source,
    get_youtube_articles_for_channel,
    get_youtube_articles_for_date,
    get_youtube_digest_for_date,
    get_youtube_digest_videos,
    get_youtube_channel_counts_for_date,
    get_recent_youtube_articles_for_channel,
    get_recent_youtube_articles,
)
from app.scraper.service import run_scrape
from app.scraper.youtube.service import run_youtube_scrape
from app.summarizer.service import run_summarization

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="app/web/templates")

# ---------------------------------------------------------------------------
# Jinja2 Markdown Filter
# ---------------------------------------------------------------------------

def _render_inline(text: str) -> str:
    """Render inline markdown: **bold**, *italic*, [text](url) and [[text]](url) links."""
    # Double-bracket links: [[text]](url) — keeps brackets visible
    text = re.sub(r'\[\[(.+?)\]\]\((.+?)\)', r'<a href="\2" target="_blank" rel="noopener">[\1]</a>', text)
    # Standard markdown links: [text](url)
    text = re.sub(r'(?<!\[)\[(.+?)\]\((.+?)\)', r'<a href="\2" target="_blank" rel="noopener">\1</a>', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'__(.+?)__', r'<strong>\1</strong>', text)
    return text

def render_markdown(text: str) -> str:
    """Render standard Markdown to HTML.

    Supports: ## headings, **bold**, - or * bullet lists, regular paragraphs.
    """
    if not text:
        return ""
    parts = []
    for para in text.split('\n\n'):
        para = para.strip()
        if not para:
            continue
        lines = para.split('\n')
        first = lines[0].strip()

        # Headings — may have trailing bullet lines in same paragraph
        if first.startswith('## '):
            parts.append(f'<h2>{_render_inline(first[3:])}</h2>')
            _append_trailing_content(parts, lines)
        elif first.startswith('# '):
            parts.append(f'<h2>{_render_inline(first[2:])}</h2>')
            _append_trailing_content(parts, lines)
        elif first.startswith('### '):
            parts.append(f'<h3>{_render_inline(first[4:])}</h3>')
            _append_trailing_content(parts, lines)

        # Bullet list — every line starts with - or *
        elif _is_bullet_list(lines):
            items = ''.join(
                f'<li>{_render_inline(_clean_bullet(l))}</li>'
                for l in lines if l.strip()
            )
            parts.append(f'<ul>{items}</ul>')

        # Regular paragraph
        else:
            rendered = '<br>'.join(_render_inline(l) for l in lines)
            parts.append(f'<p>{rendered}</p>')
    return '\n'.join(parts)

def _append_trailing_content(parts: list, lines: list[str]) -> None:
    """If a heading paragraph has trailing bullet lines, render them as a list."""
    rest = [l.strip() for l in lines[1:] if l.strip()]
    if rest and _is_bullet_list(rest):
        items = ''.join(
            f'<li>{_render_inline(_clean_bullet(l))}</li>' for l in rest
        )
        parts.append(f'<ul>{items}</ul>')
    elif rest:
        parts.append(f'<p>{"<br>".join(_render_inline(l) for l in rest)}</p>')

def _is_bullet_list(lines: list[str]) -> bool:
    """Check if all non-empty lines start with a bullet marker."""
    non_empty = [l.strip() for l in lines if l.strip()]
    if not non_empty:
        return False
    return all(l[0] in '-*\u2022' for l in non_empty)

def _clean_bullet(line: str) -> str:
    """Strip leading bullet marker and whitespace from a line."""
    s = line.strip()
    while s and s[0] in '-*\u2022':
        s = s[1:]
    return s.strip()

templates.env.filters["markdown"] = render_markdown

# ---------------------------------------------------------------------------
# Simple session-based auth (for manual triggers)
# ---------------------------------------------------------------------------

SESSIONS: dict[str, datetime] = {}  # token → expiry

# Track background job progress: date → status message
_job_status: dict[str, str] = {}

def _set_job_status(key: str, msg: str) -> None:
    _job_status[key] = msg

def _clear_job_status(key: str) -> None:
    _job_status.pop(key, None)


def _check_session(request: Request) -> bool:
    token = request.cookies.get("session")
    if token and token in SESSIONS:
        if SESSIONS[token] > datetime.utcnow():
            return True
        del SESSIONS[token]
    return False


# ---------------------------------------------------------------------------
# Public routes
# ---------------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Homepage — shows today's digest."""
    today = _today_ist_str()
    conn = get_db()
    try:
        digest = get_digest_for_date(conn, today)
        digest_articles = []
        if digest:
            digest_articles = get_digest_articles(conn, digest["id"])

        recent_articles = get_recent_articles(conn, limit=10)
        last_scrape = get_last_scrape(conn)
        prev_date, next_date = get_adjacent_dates(conn, today)

        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "digest": digest,
                "digest_articles": digest_articles,
                "recent_articles": recent_articles,
                "last_scrape": last_scrape,
                "prev_date": prev_date,
                "next_date": next_date,
                "today_str": today,
                "today_pretty": _format_date_pretty(today),
                "scrape_time": f"{settings.scrape_cron_hour:02d}:{settings.scrape_cron_minute:02d}",
            },
        )
    finally:
        conn.close()


@router.get("/digest/{date_str}", response_class=HTMLResponse)
async def digest_detail(request: Request, date_str: str):
    """View a digest for a specific date."""
    conn = get_db()
    try:
        digest = get_digest_for_date(conn, date_str)
        if not digest:
            raise HTTPException(status_code=404, detail="Digest not found for this date")

        digest_articles = get_digest_articles(conn, digest["id"])
        prev_date, next_date = get_adjacent_dates(conn, date_str)

        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "digest": digest,
                "digest_articles": digest_articles,
                "recent_articles": [],
                "last_scrape": None,
                "prev_date": prev_date,
                "next_date": next_date,
                "today_str": date_str,
                "today_pretty": _format_date_pretty(date_str),
                "scrape_time": f"{settings.scrape_cron_hour:02d}:{settings.scrape_cron_minute:02d}",
            },
        )
    finally:
        conn.close()


@router.get("/article/{article_id}", response_class=HTMLResponse)
async def article_detail(request: Request, article_id: int):
    """View a single article with its full summary."""
    conn = get_db()
    try:
        article = get_article(conn, article_id)
        if not article:
            raise HTTPException(status_code=404, detail="Article not found")

        return templates.TemplateResponse(
            request,
            "article.html",
            {
                "article": article,
            },
        )
    finally:
        conn.close()


@router.get("/history", response_class=HTMLResponse)
async def history(
    request: Request,
    year: Optional[int] = None,
    month: Optional[int] = None,
):
    """Browse past digests by year/month."""
    conn = get_db()
    try:
        years = get_digest_years(conn)

        # Default to current year if none selected
        if not year and years:
            year = years[0]
        elif not year:
            year = datetime.utcnow().year

        digests = get_all_digests(conn, year=year, month=month)

        return templates.TemplateResponse(
            request,
            "history.html",
            {
                "digests": digests,
                "years": years,
                "selected_year": year,
                "selected_month": month,
            },
        )
    finally:
        conn.close()


@router.get("/sources", response_class=HTMLResponse)
async def sources_list(request: Request):
    """List all RSS sources and their status."""
    conn = get_db()
    try:
        sources = get_all_sources(conn)
        return templates.TemplateResponse(
            request,
            "sources.html",
            {
                "sources": sources,
            },
        )
    finally:
        conn.close()


@router.get("/health")
async def health():
    """Health check endpoint."""
    return JSONResponse({"status": "ok", "timestamp": datetime.utcnow().isoformat()})


# ---------------------------------------------------------------------------
# YouTube Routes
# ---------------------------------------------------------------------------


@router.get("/youtube", response_class=HTMLResponse)
async def youtube_daily(request: Request, channel: int | None = None):
    """YouTube insights — daily digest view with vertical channel sidebar.

    All Channels: shows the synthesized YouTube digest card + collapsible video footnotes.
    Per-channel: shows the same digest (filtered footnotes) or recent videos if channel
                 hasn't posted today.
    """
    conn = get_db()
    try:
        today = _today_ist_str()
        channels = get_youtube_sources(conn)
        channel_counts = get_youtube_channel_counts_for_date(conn, today)
        last_scrape = get_last_scrape(conn)

        digest = None
        digest_videos = []
        recent_videos = []
        display_date = today

        if channel:
            # ── Per-channel view ──
            digest = get_youtube_digest_for_date(conn, today)
            if digest:
                display_date = digest["date"]
                all_videos = get_youtube_digest_videos(conn, digest["id"])
                digest_videos = [v for v in all_videos if v.get("source_id") == channel]

            if not digest_videos:
                recent_videos = get_recent_youtube_articles_for_channel(conn, channel, days=7)
        else:
            # ── All Channels view ──
            digest = get_youtube_digest_for_date(conn, today)
            if digest:
                display_date = digest["date"]
                digest_videos = get_youtube_digest_videos(conn, digest["id"])
            else:
                recent_videos = get_recent_youtube_articles(conn, limit=20, days=7)

        return templates.TemplateResponse(
            request,
            "youtube.html",
            {
                "channels": channels,
                "channel_counts": channel_counts,
                "selected_channel": channel,
                "digest": digest,
                "digest_videos": digest_videos,
                "recent_videos": recent_videos,
                "last_scrape": last_scrape,
                "today_str": today,
                "today_pretty": _format_date_pretty(today),
                "display_date": display_date,
                "display_date_pretty": _format_date_pretty(display_date),
                "scrape_time": f"{settings.scrape_cron_hour:02d}:{settings.scrape_cron_minute:02d}",
            },
        )
    finally:
        conn.close()


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Unified settings page for RSS and YouTube sources."""
    if not _check_session(request):
        return RedirectResponse(url="/login", status_code=303)

    conn = get_db()
    try:
        rss_sources = [s for s in get_all_sources(conn) if s.get("category") != "youtube"]
        youtube_sources = get_youtube_sources(conn)
        return templates.TemplateResponse(
            request,
            "settings.html",
            {
                "rss_sources": rss_sources,
                "youtube_sources": youtube_sources,
            },
        )
    finally:
        conn.close()


@router.post("/api/youtube/sources")
async def api_add_youtube_source(request: Request):
    """Add a new YouTube channel by @handle or channel URL."""
    if not _check_session(request):
        raise HTTPException(status_code=401)

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    handle = (body.get("handle") or "").strip()
    if not handle:
        raise HTTPException(status_code=400, detail="Missing handle or channel URL")

    # Resolve handle to channel ID
    from app.scraper.youtube.service import _resolve_channel_id, _get_rss_url

    channel_id = _resolve_channel_id(handle)
    if not channel_id:
        raise HTTPException(
            status_code=400,
            detail=f"Could not resolve channel: {handle}. Please provide a valid @handle or channel URL.",
        )

    # Check if already added
    conn = get_db()
    try:
        feed_url = _get_rss_url(channel_id)
        existing = conn.execute(
            "SELECT id, category FROM sources WHERE feed_url = ?", (feed_url,)
        ).fetchone()
        if existing:
            if existing["category"] == "youtube":
                raise HTTPException(
                    status_code=409,
                    detail=f"Channel already added (source #{existing['id']}).",
                )
            # Source exists with non-youtube category — recategorize it
            conn.execute(
                "UPDATE sources SET category = 'youtube', is_active = 1 WHERE id = ?",
                (existing["id"],),
            )
            conn.commit()
            return JSONResponse({
                "ok": True,
                "source_id": existing["id"],
                "recategorized": True,
            })

        # Fetch channel name from RSS
        import feedparser
        channel_name = handle
        try:
            parsed = feedparser.parse(feed_url)
            if parsed.feed.get("title"):
                channel_name = parsed.feed.title
        except Exception:
            pass

        source_id = upsert_youtube_source(
            conn,
            name=channel_name,
            channel_id=channel_id,
            channel_url=f"https://www.youtube.com/channel/{channel_id}",
        )
        conn.commit()

        return JSONResponse({
            "ok": True,
            "source_id": source_id,
            "channel_name": channel_name,
            "channel_id": channel_id,
        })
    finally:
        conn.close()


@router.post("/api/youtube/sources/{source_id}/toggle")
async def api_toggle_youtube_source(request: Request, source_id: int):
    """Toggle a YouTube channel active/inactive."""
    if not _check_session(request):
        raise HTTPException(status_code=401)

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id, is_active FROM sources WHERE id = ? AND category = 'youtube'",
            (source_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="YouTube source not found")

        new_state = 0 if row["is_active"] else 1
        update_source_active(conn, source_id, bool(new_state))
        conn.commit()
        return JSONResponse({"ok": True, "is_active": bool(new_state)})
    finally:
        conn.close()


@router.delete("/api/youtube/sources/{source_id}")
async def api_delete_youtube_source(request: Request, source_id: int):
    """Delete a YouTube channel source."""
    if not _check_session(request):
        raise HTTPException(status_code=401)

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id FROM sources WHERE id = ? AND category = 'youtube'",
            (source_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="YouTube source not found")

        delete_source(conn, source_id)
        conn.commit()
        return JSONResponse({"ok": True})
    finally:
        conn.close()


@router.post("/admin/youtube/scrape")
async def trigger_youtube_scrape(request: Request):
    """Manually trigger a YouTube scrape run in the background."""
    if not _check_session(request):
        raise HTTPException(status_code=401)

    def _run():
        _set_job_status("youtube", "Scraping YouTube channels...")
        try:
            stats = run_youtube_scrape(
                on_progress=lambda msg: _set_job_status("youtube", msg),
            )
            new = stats.get("videos_new", 0)
            ok = stats.get("channels_success", 0)
            total = stats.get("channels_total", 0)
            _set_job_status("youtube", f"Done — {new} videos from {ok}/{total} channels")
            logger.info(f"Background YouTube scrape complete: {stats}")

            # Auto-trigger summarization if we got new videos
            if new > 0:
                _set_job_status("youtube", f"Done — {new} videos. Starting summarization...")
                sum_stats = run_summarization()
                logger.info(f"YouTube summarization done: {sum_stats}")
                _set_job_status(
                    "youtube",
                    f"Done — {new} videos from {ok}/{total} channels, summarized"
                )
        except Exception as e:
            _set_job_status("youtube", f"Failed: {str(e)[:100]}")
            logger.error(f"Background YouTube scrape failed: {e}")

    threading.Thread(target=_run, daemon=True).start()

    return JSONResponse({"ok": True, "status": "started"})


# ---------------------------------------------------------------------------
# Source Management API
# ---------------------------------------------------------------------------


@router.post("/api/sources")
async def api_add_source(request: Request):
    """Add a new RSS source with URL validation."""
    if not _check_session(request):
        raise HTTPException(status_code=401)

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    name = (body.get("name") or "").strip()
    feed_url = (body.get("feed_url") or "").strip()
    site_url = (body.get("site_url") or "").strip()
    category = (body.get("category") or "").strip()

    if not feed_url:
        raise HTTPException(status_code=400, detail="feed_url is required")
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    # Validate URL by attempting to parse it as a feed
    import feedparser
    parsed = feedparser.parse(feed_url)
    if parsed.bozo and not parsed.entries:
        raise HTTPException(
            status_code=400,
            detail=f"URL does not appear to be a valid RSS/Atom feed: {feed_url}",
        )

    conn = get_db()
    try:
        source_id = upsert_source(conn, name=name, feed_url=feed_url,
                                   site_url=site_url, category=category)
        conn.commit()
        return JSONResponse(
            {"ok": True, "id": source_id, "name": name},
            status_code=201,
        )
    finally:
        conn.close()


@router.delete("/api/sources/{source_id}")
async def api_delete_source(request: Request, source_id: int):
    """Delete a source and cascade-delete all its articles."""
    if not _check_session(request):
        raise HTTPException(status_code=401)

    conn = get_db()
    try:
        articles_deleted = delete_source(conn, source_id)
        conn.commit()
        return JSONResponse({
            "ok": True,
            "articles_deleted": articles_deleted,
        })
    finally:
        conn.close()


@router.patch("/api/sources/{source_id}")
async def api_toggle_source(request: Request, source_id: int):
    """Toggle a source active/inactive."""
    if not _check_session(request):
        raise HTTPException(status_code=401)

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    is_active = body.get("is_active", True)

    conn = get_db()
    try:
        update_source_active(conn, source_id, is_active)
        conn.commit()
        return JSONResponse({"ok": True, "is_active": is_active})
    finally:
        conn.close()


@router.post("/api/sources/{source_id}/test")
async def api_test_source(request: Request, source_id: int):
    """Scrape and summarize a single source for testing."""
    if not _check_session(request):
        raise HTTPException(status_code=401)

    def _run():
        try:
            scrape_stats = run_scrape(
                source_ids=[source_id],
                on_progress=lambda msg: _set_job_status(f"test-{source_id}", msg),
            )
            logger.info(f"Test scrape complete for source {source_id}: {scrape_stats}")
            if scrape_stats.get("articles_new", 0) > 0:
                sum_stats = run_summarization(
                    source_id=source_id,
                    on_progress=lambda msg: _set_job_status(f"test-{source_id}", msg),
                )
                logger.info(f"Test summarize complete for source {source_id}: {sum_stats}")
                # Digest is already generated by run_summarization's orphan detection
                _set_job_status(f"test-{source_id}", f"✅ Done — {scrape_stats.get('articles_new', 0)} scraped, {sum_stats.get('articles_processed', 0)} summarized")
        except Exception as e:
            logger.error(f"Test run failed for source {source_id}: {e}")
            _set_job_status(f"test-{source_id}", f"❌ Failed: {str(e)[:100]}")

    threading.Thread(target=_run, daemon=True).start()

    return JSONResponse({"ok": True, "status": "started"})


@router.get("/api/sources/{source_id}")
async def api_get_source(request: Request, source_id: int):
    """Get a single source with article count."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM sources WHERE id = ?", (source_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Source not found")
        source = dict(row)
        count_row = conn.execute(
            "SELECT COUNT(*) as cnt FROM articles WHERE source_id = ?",
            (source_id,),
        ).fetchone()
        source["article_count"] = count_row["cnt"]
        return JSONResponse(source)
    finally:
        conn.close()


@router.get("/api/sources/{source_id}/articles")
async def api_get_source_articles(
    request: Request, source_id: int, limit: int = 5
):
    """Get recent articles for a source."""
    conn = get_db()
    try:
        articles = get_articles_for_source(conn, source_id, limit=limit)
        return JSONResponse({"articles": articles})
    finally:
        conn.close()


@router.put("/api/sources/{source_id}")
async def api_edit_source(request: Request, source_id: int):
    """Edit a source's name, feed_url, site_url, or category."""
    if not _check_session(request):
        raise HTTPException(status_code=401)

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    name = body.get("name")
    feed_url = body.get("feed_url")
    site_url = body.get("site_url")
    category = body.get("category")

    if feed_url is not None:
        feed_url = feed_url.strip() or None

    conn = get_db()
    try:
        update_source(
            conn, source_id,
            name=name.strip() if name else None,
            feed_url=feed_url,
            site_url=site_url.strip() if site_url else None,
            category=category.strip() if category else None,
        )
        conn.commit()
        return JSONResponse({"ok": True})
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Auth-protected routes (manual triggers)
# ---------------------------------------------------------------------------


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Simple login form."""
    return templates.TemplateResponse(
        request,
        "login.html",
        {},
    )


@router.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    """Handle login."""
    if username == settings.web_username and password == settings.web_password:
        token = secrets.token_hex(32)
        SESSIONS[token] = datetime.utcnow() + timedelta(hours=24)
        response = RedirectResponse(url="/admin", status_code=303)
        response.set_cookie("session", token, httponly=True, max_age=86400)
        return response
    return templates.TemplateResponse(
        request,
        "login.html",
        {"error": "Invalid username or password"},
        status_code=401,
    )


@router.get("/admin", response_class=HTMLResponse)
async def admin_panel(request: Request):
    """Redirect to unified Settings page."""
    return RedirectResponse(url="/settings", status_code=301)


@router.post("/admin/scrape")
async def trigger_scrape(request: Request):
    """Manually trigger a scrape run in the background."""
    if not _check_session(request):
        raise HTTPException(status_code=401)

    try:
        body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    except Exception:
        body = {}

    start_date = body.get("start_date") or None
    end_date = body.get("end_date") or None

    def _run():
        _set_job_status("scrape", "Scraping feeds...")
        try:
            stats = run_scrape(
                start_date=start_date, end_date=end_date,
                on_progress=lambda msg: _set_job_status("scrape", msg),
            )
            new = stats.get("articles_new", 0)
            ok = stats.get("feeds_success", 0)
            total = stats.get("feeds_total", 0)
            _set_job_status("scrape", f"✅ Done — {new} articles from {ok}/{total} feeds")
            logger.info(f"Background scrape complete: {stats}")
        except Exception as e:
            _set_job_status("scrape", f"❌ Failed: {str(e)[:100]}")
            logger.error(f"Background scrape failed: {e}")

    threading.Thread(target=_run, daemon=True).start()

    return JSONResponse({
        "ok": True,
        "status": "started",
        "start_date": start_date,
        "end_date": end_date,
    })


@router.post("/admin/summarize")
async def trigger_summarize(request: Request):
    """Manually trigger summarization in the background."""
    if not _check_session(request):
        raise HTTPException(status_code=401)

    def _run():
        _set_job_status("summarize", "Starting summarization...")
        try:
            stats = run_summarization(
                on_progress=lambda msg: _set_job_status("summarize", msg),
            )
            processed = stats.get("articles_processed", 0)
            failed = stats.get("articles_failed", 0)
            _set_job_status("summarize", f"✅ Done — {processed} processed, {failed} failed")
            logger.info(f"Background summarization complete: {stats}")
        except Exception as e:
            _set_job_status("summarize", f"❌ Failed: {str(e)[:100]}")
            logger.error(f"Background summarization failed: {e}")

    threading.Thread(target=_run, daemon=True).start()

    return JSONResponse({
        "ok": True,
        "status": "started",
    })


@router.post("/admin/regenerate-digest/{date_str}")
async def regenerate_digest(request: Request, date_str: str):
    """Regenerate the daily digest for a specific date.
    Accepts optional query params: provider (gemini|groq|deepseek) and model."""
    if not _check_session(request):
        raise HTTPException(status_code=401)

    provider = request.query_params.get("provider") or None
    model = request.query_params.get("model") or None

    from app.summarizer.service import _generate_daily_digest

    def _run():
        conn = get_db()
        try:
            _set_job_status(date_str, "Building prompt...")
            _generate_daily_digest(
                conn, date_str,
                provider=provider, model=model,
                on_progress=lambda msg: _set_job_status(date_str, msg),
            )
            conn.commit()
            _set_job_status(date_str, "✅ Done")
            logger.info(f"Digest regenerated for {date_str}")
        except Exception as e:
            _set_job_status(date_str, f"❌ Failed: {str(e)[:100]}")
            logger.error(f"Digest regeneration failed for {date_str}: {e}")
        finally:
            conn.close()
        # Auto-clear status after 10s so the regen button reappears
        import time
        time.sleep(10)
        _clear_job_status(date_str)

    threading.Thread(target=_run, daemon=True).start()

    return JSONResponse({
        "ok": True,
        "status": "started",
        "date": date_str,
        "provider": provider,
        "model": model,
    })


@router.get("/admin/status")
async def admin_status(request: Request):
    """JSON endpoint showing per-date scrape/summarize/digest status."""
    if not _check_session(request):
        raise HTTPException(status_code=401)

    conn = get_db()
    try:
        # Per-date article and digest status
        rows = conn.execute("""
            SELECT
                date(a.fetched_at) as d,
                COUNT(*) as total,
                SUM(CASE WHEN a.status = 'raw' THEN 1 ELSE 0 END) as raw_count,
                SUM(CASE WHEN a.status = 'summarized' THEN 1 ELSE 0 END) as summarized,
                SUM(CASE WHEN a.status = 'failed' THEN 1 ELSE 0 END) as failed,
                SUM(CASE WHEN a.status = 'summarizing' THEN 1 ELSE 0 END) as in_progress,
                dg.id IS NOT NULL as has_digest
            FROM articles a
            LEFT JOIN daily_digests dg ON date(a.fetched_at) = dg.date
            GROUP BY d
            ORDER BY d DESC
            LIMIT 60
        """).fetchall()

        dates = []
        for r in rows:
            dates.append({
                "date": r["d"],
                "total": r["total"],
                "raw": r["raw_count"],
                "summarized": r["summarized"],
                "failed": r["failed"],
                "in_progress": r["in_progress"],
                "has_digest": bool(r["has_digest"]),
            })

        # LLM usage stats
        from app.summarizer.llm import get_usage_stats
        llm_stats = get_usage_stats()

        # Provider distribution
        provider_rows = conn.execute("""
            SELECT llm_provider, COUNT(*) as cnt
            FROM articles
            WHERE status = 'summarized' AND llm_provider != ''
            GROUP BY llm_provider
        """).fetchall()
        providers = {r["llm_provider"]: r["cnt"] for r in provider_rows}

        return JSONResponse({
            "dates": dates,
            "llm": llm_stats,
            "providers": providers,
            "jobs": dict(_job_status),
        })
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _today_ist_str() -> str:
    ist = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(ist).strftime("%Y-%m-%d")


def _format_date_pretty(date_str: str) -> str:
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%d %B %Y")
    except ValueError:
        return date_str
