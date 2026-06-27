"""Dataclass models for the application."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Source:
    id: int | None = None
    name: str = ""
    feed_url: str = ""
    site_url: str = ""
    category: str = ""
    source_type: str = "rss"
    is_active: bool = True
    last_fetched_at: datetime | None = None
    created_at: datetime | None = None
    archived_at: datetime | None = None


@dataclass
class Article:
    id: int | None = None
    source_id: int | None = None
    url: str = ""
    title: str = ""
    snippet: str = ""
    raw_text: str = ""
    summary_text: str = ""
    author: str = ""
    published_at: datetime | None = None
    published_date_ist: str | None = None
    fetched_at: datetime | None = None
    status: str = "raw"  # 'raw' | 'summarizing' | 'summarized' | 'failed'
    chunk_count: int = 0
    error_message: str = ""


@dataclass
class DailyDigest:
    id: int | None = None
    date: str = ""  # ISO date string, e.g. "2026-05-29"
    title: str = ""
    summary_text: str = ""
    article_count: int = 0
    source_count: int = 0
    status: str = "generated"  # 'generated' | 'regenerating'
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class ScrapeLog:
    id: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    feeds_total: int = 0
    feeds_success: int = 0
    feeds_failed: int = 0
    articles_new: int = 0
    articles_skipped: int = 0
    error_details: str = ""  # JSON blob
    created_at: datetime | None = None
