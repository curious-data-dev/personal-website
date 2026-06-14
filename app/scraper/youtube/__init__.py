"""YouTube scraping pipeline — channel discovery via RSS, transcript extraction."""

from app.scraper.youtube.service import run_youtube_scrape

__all__ = ["run_youtube_scrape"]
