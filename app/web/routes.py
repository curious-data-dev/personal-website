"""FastAPI route definitions for the web interface."""

import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Request, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

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
)
from app.scraper.service import run_scrape
from app.summarizer.service import run_summarization

router = APIRouter()
templates = Jinja2Templates(directory="app/web/templates")

# ---------------------------------------------------------------------------
# Simple session-based auth (for manual triggers)
# ---------------------------------------------------------------------------

SESSIONS: dict[str, datetime] = {}  # token → expiry


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

        # Also get recent articles for a sidebar/overview
        recent_articles = get_recent_articles(conn, limit=10)

        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "digest": digest,
                "digest_articles": digest_articles,
                "recent_articles": recent_articles,
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
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "digest": digest,
                "digest_articles": digest_articles,
                "recent_articles": [],
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
    """Manually trigger a scrape run. Accepts optional date range in JSON body."""
    if not _check_session(request):
        raise HTTPException(status_code=401)

    try:
        body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    except Exception:
        body = {}

    start_date = body.get("start_date") or None
    end_date = body.get("end_date") or None

    try:
        stats = run_scrape(start_date=start_date, end_date=end_date)
        return JSONResponse({
            "ok": True,
            "stats": stats,
        })
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/admin/summarize")
async def trigger_summarize(request: Request):
    """Manually trigger summarization."""
    if not _check_session(request):
        raise HTTPException(status_code=401)

    try:
        stats = run_summarization()
        return JSONResponse({
            "ok": True,
            "stats": stats,
        })
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


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

        return JSONResponse({
            "dates": dates,
            "llm": llm_stats,
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
