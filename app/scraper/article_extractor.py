"""Article text extraction with smart trafilatura → Playwright fallback.

Strategy:
1. Fast path: trafilatura (HTTP requests, no browser) — works for most sites.
2. Slow path: Playwright headless Chromium — for JS-rendered / SPA sites.
"""

import asyncio
import concurrent.futures
import logging
from typing import Optional

import trafilatura
from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

# Minimum characters to consider an extraction "successful" before falling back
MIN_TEXT_LENGTH = 300
PLAYWRIGHT_TIMEOUT_MS = 30000


def extract_article_text(url: str) -> Optional[str]:
    """Extract article text. Works in both sync and async contexts."""
    try:
        loop = asyncio.get_running_loop()
        # Already inside an event loop (FastAPI) — run in a separate thread
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, _extract_article_text_async(url)).result()
    except RuntimeError:
        # No running loop — safe to use asyncio.run()
        return asyncio.run(_extract_article_text_async(url))


async def _extract_article_text_async(url: str) -> Optional[str]:
    """Fast path first (trafilatura), browser only when needed."""

    # --- Fast path: trafilatura ---
    try:
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            text = trafilatura.extract(
                downloaded,
                include_comments=False,
                include_tables=False,
                no_fallback=False,
            )
            if text and len(text.strip()) > MIN_TEXT_LENGTH:
                logger.debug(f"trafilatura extracted {len(text)} chars from {url}")
                return text.strip()
            elif text:
                logger.debug(
                    f"trafilatura returned short text ({len(text)} chars) for {url}"
                )
    except Exception as e:
        logger.warning(f"trafilatura failed for {url}: {e}")

    # --- Slow path: Playwright ---
    logger.info(f"Falling back to Playwright for {url}")
    try:
        text = await _extract_with_playwright(url)
        if text and len(text.strip()) > 0:
            return text.strip()
    except Exception as e:
        logger.error(f"Playwright extraction failed for {url}: {e}")

    return None


async def _extract_with_playwright(url: str) -> Optional[str]:
    """Use headless Chromium to render the page and extract article text.

    Tries to find <article> or main content area first,
    then falls back to full body text.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        page = await context.new_page()

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=PLAYWRIGHT_TIMEOUT_MS)
            # Wait a bit for any dynamic content to load
            await asyncio.sleep(2)

            # Try article-specific selectors
            text = await page.evaluate("""
                () => {
                    const selectors = [
                        'article', '[role="main"]', 'main',
                        '.post-content', '.article-content', '.entry-content',
                        '#article-body', '.story-body', '.content-body'
                    ];
                    for (const sel of selectors) {
                        const el = document.querySelector(sel);
                        if (el && el.innerText.length > 200) {
                            return el.innerText;
                        }
                    }
                    // Fallback: body text
                    return document.body ? document.body.innerText : '';
                }
            """)

            # Remove navigation/boilerplate by truncating at common footer patterns
            text = _trim_boilerplate(text)
            logger.debug(f"Playwright extracted {len(text)} chars from {url}")
            return text

        finally:
            await browser.close()


def _trim_boilerplate(text: str) -> str:
    """Remove common footer/header boilerplate from extracted text."""
    # Stop at common end-of-article markers
    cut_patterns = [
        "\nShare\n", "\nShare this", "\nRelated\n", "\nRelated Articles",
        "\nRead also\n", "\nAlso Read\n", "\nSubscribe\n",
        "\nComments\n", "\n© ", "\nCopyright",
    ]
    for pattern in cut_patterns:
        idx = text.find(pattern)
        if idx > 500:  # Don't cut too early
            text = text[:idx]
            break
    return text.strip()
