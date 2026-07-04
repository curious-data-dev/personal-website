# TOC & Sources Right Sidebar — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fixed right sidebar with auto-generated Table of Contents and numbered Sources list on all content pages.

**Architecture:** Server-side extraction of headings and citation links from existing digest/article markdown text. No database changes. The `render_markdown` filter gains heading `id` attributes. New helper functions extract TOC and source data. Route handlers pass structured data to templates. The sidebar renders fully server-side — zero JavaScript DOM crawling, zero flash.

**Tech Stack:** Python 3.12, FastAPI, Jinja2, Tailwind CSS (inline), re (stdlib)

## Global Constraints

- No database schema changes
- No regeneration of existing digests/backfills needed
- Works immediately with all historical content
- Styling matches existing conventions: Inter font, `--ink`/`--text-muted`/`--border`/`--bg` CSS variables, `border-gray-200 dark:border-slate-800`
- Right sidebar hidden below `xl` breakpoint (1280px)
- TOC includes `h2` and `h3` (exhaustive)
- Sources are numbered `[[N]](url)` citations extracted from digest text

---

### Task 1: Add heading ID generation to markdown renderer

**Files:**
- Modify: `app/web/routes.py:63-107` (render_markdown function area)
- Modify: `app/web/routes.py:120` (add Jinja2 filter `make_anchor`)

**Interfaces:**
- Produces: `_make_anchor(text: str) -> str` — generates URL-safe anchor from heading text
- Produces: modified `render_markdown()` — adds `id="..."` attributes to `<h2>` and `<h3>` tags

- [ ] **Step 1: Add `_make_anchor` helper function and apply it in `render_markdown`**

In `app/web/routes.py`, add `_make_anchor` right after `_clean_bullet` (around line 94). Then modify the three heading blocks in `render_markdown`.

The anchor generator:

```python
def _make_anchor(text: str) -> str:
    """Generate a URL-safe anchor ID from heading text.

    Strips inline markdown tokens (*, **) and reduces to
    lowercase alphanumeric segments joined by hyphens.
    """
    # Strip inline markdown tokens before building anchor
    clean = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    clean = re.sub(r'__(.+?)__', r'\1', clean)
    clean = re.sub(r'\*(.+?)\*', r'\1', clean)
    clean = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', clean)
    return re.sub(r'[^a-z0-9]+', '-', clean.lower()).strip('-')
```

The three heading blocks in `render_markdown` change from:

```python
        if first.startswith('## '):
            parts.append(f'<h2>{_render_inline(first[3:])}</h2>')
            _append_trailing_content(parts, lines)
        elif first.startswith('# '):
            parts.append(f'<h2>{_render_inline(first[2:])}</h2>')
            _append_trailing_content(parts, lines)
        elif first.startswith('### '):
            parts.append(f'<h3>{_render_inline(first[4:])}</h3>')
            _append_trailing_content(parts, lines)
```

To:

```python
        if first.startswith('## '):
            raw = first[3:]
            parts.append(f'<h2 id="{_make_anchor(raw)}">{_render_inline(raw)}</h2>')
            _append_trailing_content(parts, lines)
        elif first.startswith('# '):
            raw = first[2:]
            parts.append(f'<h2 id="{_make_anchor(raw)}">{_render_inline(raw)}</h2>')
            _append_trailing_content(parts, lines)
        elif first.startswith('### '):
            raw = first[4:]
            parts.append(f'<h3 id="{_make_anchor(raw)}">{_render_inline(raw)}</h3>')
            _append_trailing_content(parts, lines)
```

- [ ] **Step 2: Register `_make_anchor` as a Jinja2 filter**

After the existing line `templates.env.filters["markdown"] = render_markdown` (line ~120), add:

```python
templates.env.filters["make_anchor"] = _make_anchor
```

- [ ] **Step 3: Run existing tests to verify no regressions**

```bash
python -m pytest tests/ -x -q
```

Expected: all existing tests pass. The heading ID addition should not break any test assertions.

- [ ] **Step 4: Commit**

```bash
git add app/web/routes.py
git commit -m "feat: add heading id generation to markdown renderer"
```

---

### Task 2: Add TOC and citation extraction helpers

**Files:**
- Modify: `app/web/routes.py` (add `TocEntry`, `SourceEntry`, `extract_toc`, `extract_citations`)

**Interfaces:**
- Produces: `TocEntry(level: int, text: str, anchor: str)` — dataclass for TOC items
- Produces: `SourceEntry(number: int, url: str, title: str)` — dataclass for source items
- Produces: `extract_toc(text: str) -> list[TocEntry]` — extracts `##`/`###` headings from markdown
- Produces: `extract_citations(text: str) -> list[SourceEntry]` — extracts `[[N]](url)` patterns

- [ ] **Step 1: Add imports, dataclasses, and extraction functions**

At the top of `app/web/routes.py`, add `from dataclasses import dataclass` to the imports. Then add these classes and functions after `_make_anchor` and before `SESSIONS`:

```python
from dataclasses import dataclass


@dataclass
class TocEntry:
    level: int       # 2 for ##, 3 for ###
    text: str        # raw heading text (for display, rendered inline later)
    anchor: str      # URL-safe anchor matching the id attribute


@dataclass
class SourceEntry:
    number: int      # citation number from [[N]]
    url: str         # full article URL
    title: str       # resolved article title, or domain fallback, or ''


def extract_toc(text: str) -> list[TocEntry]:
    """Extract ## and ### headings from markdown text as TOC entries."""
    entries: list[TocEntry] = []
    if not text:
        return entries
    for match in re.finditer(r'^(#{2,3})\s+(.+?)$', text, re.MULTILINE):
        level = len(match.group(1))
        raw = match.group(2).strip()
        entries.append(TocEntry(level=level, text=raw, anchor=_make_anchor(raw)))
    return entries


def extract_citations(text: str) -> list[SourceEntry]:
    """Extract [[N]](url) citation links from digest text.

    Returns sorted, deduplicated list ordered by citation number.
    """
    results: list[SourceEntry] = []
    if not text:
        return results
    for match in re.finditer(r'\[\[(\d+)\]\]\(([^)]+)\)', text):
        results.append(SourceEntry(
            number=int(match.group(1)),
            url=match.group(2),
            title='',
        ))
    # Sort by number, deduplicate by number
    seen: set[int] = set()
    unique: list[SourceEntry] = []
    for s in sorted(results, key=lambda x: x.number):
        if s.number not in seen:
            seen.add(s.number)
            unique.append(s)
    return unique
```

- [ ] **Step 2: Run tests**

```bash
python -m pytest tests/ -x -q
```

Expected: all pass. New functions are pure and don't break anything.

- [ ] **Step 3: Commit**

```bash
git add app/web/routes.py
git commit -m "feat: add TOC and citation extraction helpers"
```

---

### Task 3: Add right sidebar HTML, CSS, and JS to base.html

**Files:**
- Modify: `app/web/templates/base.html` (add sidebar markup, styles, scroll JS)

**Interfaces:**
- Consumes: template variables `toc: list[TocEntry]` and `sources: list[SourceEntry]` (passed by routes)
- Produces: right sidebar visible on `xl:` screens containing TOC + Sources sections

- [ ] **Step 1: Add right sidebar HTML structure**

Add this after the `<footer>` tag in `<main>` (around line 195, after `</footer>`), before the sidebar link styles:

```html
    {# ── Right Sidebar (TOC + Sources) ── #}
    {% if toc or sources %}
    <aside id="rightSidebar" class="hidden xl:block fixed inset-y-0 right-0 z-30 w-56 bg-white dark:bg-slate-900 border-l border-gray-200 dark:border-slate-800 overflow-y-auto">
        <div class="px-4 pt-6 pb-4">

        {# ── Table of Contents ── #}
        {% if toc %}
        <div class="mb-6">
            <h4 class="text-xs font-semibold uppercase tracking-wider text-gray-400 dark:text-slate-500 mb-3">📑 On this page</h4>
            <nav class="flex flex-col gap-0.5" id="tocNav">
            {% for entry in toc %}
                <a href="#{{ entry.anchor }}" class="toc-link block rounded-md px-2 py-1 text-sm font-medium text-gray-500 hover:text-blue-600 hover:bg-gray-50 dark:text-slate-400 dark:hover:text-blue-400 dark:hover:bg-slate-800 transition-colors{% if entry.level == 3 %} ml-3{% endif %}"
                   data-toc-target="{{ entry.anchor }}">
                    {{ entry.text | e }}
                </a>
            {% endfor %}
            </nav>
        </div>
        {% endif %}

        {# ── Sources ── #}
        {% if sources %}
        <div class="border-t border-gray-100 dark:border-slate-800 pt-5{% if not toc %} border-t-0 pt-0{% endif %}">
            <h4 class="text-xs font-semibold uppercase tracking-wider text-gray-400 dark:text-slate-500 mb-3">📡 Sources</h4>
            <ol class="flex flex-col gap-1.5 text-sm" id="sourcesList">
            {% for src in sources %}
                <li class="flex items-start gap-1.5">
                    <span class="text-xs font-bold text-blue-600 dark:text-blue-400 flex-shrink-0 mt-0.5">[{{ src.number }}]</span>
                    <a href="{{ src.url }}" target="_blank" rel="noopener"
                       class="text-gray-600 hover:text-blue-600 dark:text-slate-400 dark:hover:text-blue-400 transition-colors leading-snug break-all"
                       title="{{ src.url }}">
                        {{ src.title or src.url }}
                    </a>
                </li>
            {% endfor %}
            </ol>
        </div>
        {% endif %}

        </div>
    </aside>
    {% endif %}
```

- [ ] **Step 2: Add CSS for the right sidebar**

In the `<style>` block that already exists in base.html (near line ~72, where `--bg` / `--border` variables are defined), add these styles inside the same `<style>` tag:

```css
        /* ── Right sidebar ── */
        #rightSidebar {
            scrollbar-width: thin;
            scrollbar-color: #d1d5db transparent;
        }
        [data-theme="dark"] #rightSidebar {
            scrollbar-color: #334155 transparent;
        }

        .toc-link-active {
            color: #2563eb !important;
            background: #eff6ff !important;
        }
        [data-theme="dark"] .toc-link-active {
            color: #60a5fa !important;
            background: rgba(37,99,235,0.1) !important;
        }

        /* When right sidebar is visible, reduce main content width */
        @media (min-width: 1280px) {
            .has-right-sidebar #mainContent {
                margin-right: 14rem; /* 224px = w-56 */
            }
        }
```

- [ ] **Step 3: Add TOC scroll-spy and smooth-scroll JavaScript**

Add this inside the existing `<script>` block in base.html (before the closing `</script>` tag, near the end):

```javascript
        // ── TOC smooth scroll + active tracking ──
        (function() {
            var tocLinks = document.querySelectorAll('#tocNav .toc-link');
            if (!tocLinks.length) return;

            // Smooth scroll on click
            tocLinks.forEach(function(link) {
                link.addEventListener('click', function(e) {
                    e.preventDefault();
                    var targetId = this.getAttribute('data-toc-target');
                    var target = document.getElementById(targetId);
                    if (target) {
                        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
                        history.replaceState(null, '', '#' + targetId);
                    }
                });
            });

            // Active tracking on scroll
            var headings = [];
            tocLinks.forEach(function(link) {
                var id = link.getAttribute('data-toc-target');
                var el = document.getElementById(id);
                if (el) headings.push({ el: el, link: link });
            });

            function updateActive() {
                var scrollY = window.scrollY + 80; // offset for sticky header
                var activeLink = null;
                for (var i = headings.length - 1; i >= 0; i--) {
                    if (headings[i].el.offsetTop <= scrollY) {
                        activeLink = headings[i].link;
                        break;
                    }
                }
                tocLinks.forEach(function(l) { l.classList.remove('toc-link-active'); });
                if (activeLink) activeLink.classList.add('toc-link-active');
            }

            if (headings.length) {
                window.addEventListener('scroll', updateActive, { passive: true });
                updateActive();
            }
        })();
```

- [ ] **Step 4: Add conditional class to `<body>` when right sidebar exists**

The `has-right-sidebar` CSS class controls the main content margin. We need to apply it from the template. Since the sidebar is rendered by Jinja2 (not JS), we can conditionally add the class to `<body>`. Change the `<body>` tag from:

```html
<body class="font-sans antialiased bg-gray-50 dark:bg-slate-900 text-gray-900 dark:text-white transition-colors">
```

To:

```html
<body class="font-sans antialiased bg-gray-50 dark:bg-slate-900 text-gray-900 dark:text-white transition-colors{% if toc or sources %} has-right-sidebar{% endif %}">
```

- [ ] **Step 5: Run the app and visually check the HTML**

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open http://localhost:8000 in a browser. The sidebar should NOT appear yet (no `toc`/`sources` data is passed from routes — that's Task 4). But there should be no HTML errors or broken page.

- [ ] **Step 6: Commit**

```bash
git add app/web/templates/base.html
git commit -m "feat: add right sidebar HTML, CSS, and JS for TOC/sources"
```

---

### Task 4: Wire TOC and source data into page routes

**Files:**
- Modify: `app/web/routes.py` — `home()`, `digest_detail()`, `article_detail()`, `youtube_daily()` route handlers

**Interfaces:**
- Consumes: `extract_toc(text) -> list[TocEntry]`, `extract_citations(text) -> list[SourceEntry]`
- Produces: `"toc"` and `"sources"` keys in template context dicts

- [ ] **Step 1: Add source title resolution helper**

After `extract_citations`, add a helper that resolves article titles by URL from the digest_articles list (already fetched in the home/digest routes):

```python
def _resolve_source_titles(
    citations: list[SourceEntry],
    digest_articles: list[dict],
) -> list[SourceEntry]:
    """Resolve citation titles from the digest_articles list by URL match.

    Falls back to extracting the domain name from the URL if no match found.
    """
    # Build URL → title map from digest_articles
    url_map: dict[str, str] = {}
    for da in digest_articles:
        # digest_articles entries have keys from the DB, including 'url' if the
        # query returned it.  We match on any known URL column.
        for k in ('url', 'article_url', 'source_url'):
            u = da.get(k)
            if u and isinstance(u, str):
                url_map[u] = da.get('title', '') or ''

    for s in citations:
        if s.url in url_map and url_map[s.url]:
            s.title = url_map[s.url]
        elif not s.title:
            # Fallback: extract domain from URL
            m = re.match(r'https?://([^/]+)', s.url)
            s.title = m.group(1) if m else s.url
    return citations
```

- [ ] **Step 2: Wire data into `home()` route (~line 175)**

In the `home()` function, after fetching `digest_articles`, add:

```python
        # Extract TOC and sources from digest text
        toc: list[TocEntry] = []
        sources: list[SourceEntry] = []
        if digest and digest.get("summary_text"):
            toc = extract_toc(digest["summary_text"])
            sources = extract_citations(digest["summary_text"])
            sources = _resolve_source_titles(sources, digest_articles)
```

Then add `"toc": toc, "sources": sources,` to the `TemplateResponse` context dict.

- [ ] **Step 3: Wire data into `digest_detail()` route (~line 215)**

Same pattern as `home()` — after fetching `digest_articles`:

```python
        toc: list[TocEntry] = []
        sources: list[SourceEntry] = []
        if digest and digest.get("summary_text"):
            toc = extract_toc(digest["summary_text"])
            sources = extract_citations(digest["summary_text"])
            sources = _resolve_source_titles(sources, digest_articles)
```

Add `"toc": toc, "sources": sources,` to the `TemplateResponse` context.

- [ ] **Step 4: Wire data into `article_detail()` route (~line 247)**

The article page uses `article.summary_text` (or `raw_text` if no summary). After fetching the article:

```python
        toc: list[TocEntry] = []
        sources: list[SourceEntry] = []
        text = article.get("summary_text") or article.get("raw_text") or ""
        if text:
            toc = extract_toc(text)
            # For single article, resolve title from the article itself
            sources = extract_citations(text)
            if sources and article.get("title"):
                # Single article: all citations are this article — set title
                for s in sources:
                    s.title = article.get("title", "")
```

Add `"toc": toc, "sources": sources,` to the `TemplateResponse` context.

- [ ] **Step 5: Wire data into `youtube_daily()` route (~line 330)**

In the YouTube route, after the `digest` is fetched:

```python
        toc: list[TocEntry] = []
        sources: list[SourceEntry] = []
        if digest and digest.get("summary_text"):
            toc = extract_toc(digest["summary_text"])
            sources = extract_citations(digest["summary_text"])
            if sources and digest_videos:
                # Resolve titles from digest_videos by URL
                url_map: dict[str, str] = {}
                for v in digest_videos:
                    u = v.get("url")
                    if u:
                        url_map[u] = v.get("title", "")
                for s in sources:
                    if s.url in url_map:
                        s.title = url_map[s.url]
                    elif not s.title:
                        m = re.match(r'https?://([^/]+)', s.url)
                        s.title = m.group(1) if m else s.url
```

Add `"toc": toc, "sources": sources,` to the `TemplateResponse` context.

- [ ] **Step 6: Run existing tests**

```bash
python -m pytest tests/ -x -q
```

Expected: all tests pass. New context variables won't break templates since they use `{% if toc %}` guards.

- [ ] **Step 7: Commit**

```bash
git add app/web/routes.py
git commit -m "feat: wire TOC and source data into page routes"
```

---

### Task 5: Integration verification

**Files:**
- No file changes — verification-only task

- [ ] **Step 1: Start the server**

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

- [ ] **Step 2: Verify Daily Digest page**

Open http://localhost:8000. Confirm:
- Right sidebar appears on the right side of the screen
- TOC lists all `##` and `###` headings from the digest
- Clicking a TOC entry smoothly scrolls to that heading
- Active TOC item highlights as you scroll
- Sources section lists numbered `[[1]](url)` citations as clickable links
- Links open in new tab
- Sidebar scrolls independently if content overflows

- [ ] **Step 3: Verify Article page**

Open an article from the digest page. Confirm:
- TOC shows headings from the article's summary/raw text
- Sources show citation links
- No right sidebar flicker — content is present on initial page load

- [ ] **Step 4: Verify dark mode**

Toggle dark mode. Confirm:
- Sidebar background switches to `dark:bg-slate-900`
- TOC links follow dark mode colors
- Active TOC item uses blue (`#60a5fa`) in dark mode
- Sources list uses correct dark mode text colors

- [ ] **Step 5: Verify responsive behavior**

Resize browser below 1280px width. Confirm right sidebar disappears. Resize back. Confirm it reappears.

- [ ] **Step 6: Verify empty states**

Visit a page with a digest that has no headings (rare but possible). Confirm TOC section gracefully hides. Visit a page where the digest has no citations. Confirm Sources section gracefully hides.

- [ ] **Step 7: Run full test suite**

```bash
python -m pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 8: Commit (if any final tweaks were made)**

```bash
git add -A
git commit -m "chore: final integration tweaks for TOC/sources sidebar"
```
