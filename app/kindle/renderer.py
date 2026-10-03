"""Render a stored digest into a self-contained HTML document.

The output mirrors the reading card on the web digest pages (the same
`render_markdown` renderer), wrapped in an <article> so the HTML→EPUB
converter extracts exactly that content and ignores any page chrome.
"""

from html import escape


def build_digest_html(digest: dict, digest_type: str, title: str) -> str:
    """Return a complete, self-contained HTML document for one digest."""
    # Imported lazily: app.web.routes imports the summarizer/scraper services,
    # so a top-level import here would create an import cycle once the Kindle
    # service is pulled in by the daily job.
    from app.web.routes import render_markdown

    if digest_type == "youtube":
        footer = (
            f"{digest.get('video_count', 0)} videos from "
            f"{digest.get('channel_count', 0)} channels"
        )
    else:
        footer = (
            f"{digest.get('article_count', 0)} articles from "
            f"{digest.get('source_count', 0)} sources"
        )

    body = render_markdown(digest.get("summary_text") or "")
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        f"<title>{escape(title)}</title>\n"
        '<meta name="author" content="Media Hub">\n'
        "</head>\n"
        "<body>\n"
        "<article>\n"
        f"{body}\n"
        f"<footer>{escape(footer)}</footer>\n"
        "</article>\n"
        "</body>\n"
        "</html>\n"
    )
