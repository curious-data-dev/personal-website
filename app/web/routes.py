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
)
from app.scraper.service import run_scrape
from app.summarizer.service import run_summarization

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="app/web/templates")

# ---------------------------------------------------------------------------
# Jinja2 Markdown Filter
# ---------------------------------------------------------------------------

def _render_inline(text: str) -> str:
    """Render inline markdown: **bold**, *italic*."""
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
                "opml_path": settings.opml_path,
            },
        )
    finally:
        conn.close()


@router.get("/health")
async def health():
    """Health check endpoint."""
    return JSONResponse({"status": "ok", "timestamp": datetime.utcnow().isoformat()})


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
    """Admin panel with manual trigger buttons."""
    if not _check_session(request):
        return RedirectResponse(url="/login", status_code=303)

    return templates.TemplateResponse(
        request,
        "admin.html",
        {},
    )


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
        try:
            stats = run_scrape(start_date=start_date, end_date=end_date)
            logger.info(f"Background scrape complete: {stats}")
        except Exception as e:
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
        try:
            stats = run_summarization()
            logger.info(f"Background summarization complete: {stats}")
        except Exception as e:
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
