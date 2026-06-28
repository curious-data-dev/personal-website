# UI Modernization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the Media Hub from custom CSS to a Minimal/SaaS aesthetic using Tailwind CSS v4 standalone CLI, applied page-by-page.

**Architecture:** Tailwind v4 standalone CLI compiles `input.css` → `output.css`. Inter font loaded from Google Fonts CDN. Templates are server-rendered Jinja2. No JS framework. Dark mode via `data-theme="dark"` attribute with Tailwind selector strategy. Mobile sidebar becomes a slide-over drawer triggered by hamburger button.

**Tech Stack:** Tailwind CSS v4 (standalone CLI), Inter font (Google Fonts CDN), Jinja2 templates, vanilla JS

## Global Constraints

- All Tailwind classes use `dark:` variants for dark mode
- Dark mode activated via `[data-theme="dark"]` selector (configured in `input.css`)
- No JavaScript framework — all interactivity is vanilla JS in `<script>` tags
- No backend changes
- Template logic (Jinja2 conditionals, loops) preserved exactly as-is — only HTML structure and classes change
- `style.css` kept alongside `output.css` until Phase 10 cleanup; both linked in `base.html`
- Inter font loaded via Google Fonts CDN: `<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">`

---

### Task 1: Tailwind CSS Setup & Configuration

**Files:**
- Create: `app/web/static/input.css`
- Create: server build/watch script (documented, not a separate file)
- Modify: `app/web/templates/base.html` (add CSS + font links to `<head>`)

**Interfaces:**
- Produces: `app/web/static/output.css` — compiled Tailwind CSS served at `/static/output.css`
- Produces: Tailwind `dark:` variant keyed off `[data-theme="dark"]` selector
- Produces: `font-sans` = Inter; `font-serif` = Georgia fallback

- [ ] **Step 1: Download Tailwind CSS standalone CLI**

Download the Tailwind v4 standalone CLI for your platform (Windows x64):
```bash
cd "C:/Users/pc/Documents/My Docs/Projects/personal-website"
# Download Windows x64 binary
curl -sLO https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-windows-x64.exe
mv tailwindcss-windows-x64.exe tailwindcss.exe
```
If curl isn't available, manually download from: https://github.com/tailwindlabs/tailwindcss/releases/latest and place `tailwindcss-windows-x64.exe` as `tailwindcss.exe` in the project root.

- [ ] **Step 2: Create the Tailwind input CSS file**

Write `app/web/static/input.css`:
```css
@import "tailwindcss";

@theme {
  --font-sans: "Inter", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --font-serif: Georgia, "Times New Roman", serif;
}

@variant dark (&:where([data-theme="dark"], [data-theme="dark"] *));
```

- [ ] **Step 3: Run Tailwind build to verify it compiles**

```bash
cd "C:/Users/pc/Documents/My Docs/Projects/personal-website"
./tailwindcss.exe -i app/web/static/input.css -o app/web/static/output.css
```

Expected: `output.css` is created, several KB in size, contains Tailwind utilities.

- [ ] **Step 4: Add Inter font and Tailwind CSS link to base.html**

Modify `app/web/templates/base.html`. In `<head>`, after `<meta name="viewport"...>`, before the existing `<link rel="stylesheet" href="/static/style.css">`:

Add:
```html
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="/static/output.css">
```

The `<head>` should now have (in order):
1. `<meta charset>`
2. `<meta viewport>`
3. `<title>`
4. `<link rel="icon">`
5. Dark-mode flash-prevention `<script>` (keep exactly as-is)
6. **New**: Google Fonts `<link>` for Inter
7. **New**: `<link rel="stylesheet" href="/static/output.css">`
8. Existing: `<link rel="stylesheet" href="/static/style.css">`
9. `{% block head_extra %}`

- [ ] **Step 5: Commit**

```bash
git add app/web/static/input.css app/web/static/output.css app/web/templates/base.html
git commit -m "feat: add Tailwind CSS v4 setup with Inter font"
```

---

### Task 2: Convert base.html Layout & Sidebar

**Files:**
- Modify: `app/web/templates/base.html` (full rewrite of body structure)

**Interfaces:**
- Consumes: `output.css` from Task 1
- Produces: Tailwind-styled layout with sidebar + main area
- Produces: Collapsible sidebar (desktop) with localStorage persistence
- Produces: Mobile hamburger + slide-over drawer
- Produces: Theme toggle (sun/moon SVG)
- Produces: YouTube subnav toggle (unchanged logic, new classes)

- [ ] **Step 1: Write the new base.html**

Replace the entire `<body>` section of `app/web/templates/base.html` (keep `<head>` as modified in Task 1). The new body:

```html
<body class="font-sans antialiased bg-gray-50 dark:bg-slate-900 text-gray-900 dark:text-white transition-colors">

    {# ── Desktop Sidebar ── #}
    <aside id="sidebar" class="fixed inset-y-0 left-0 z-40 w-60 bg-white dark:bg-slate-900 border-r border-gray-200 dark:border-slate-800 flex flex-col transition-all duration-200 overflow-y-auto overflow-x-hidden max-md:hidden">
        {# Brand row #}
        <div class="flex items-center gap-2 px-4 py-4">
            <a href="/" class="font-bold text-base text-gray-900 dark:text-white whitespace-nowrap overflow-hidden text-ellipsis flex-1 min-w-0">📰 Media Hub</a>
            <button id="sidebarToggle" title="Toggle sidebar" aria-label="Toggle sidebar"
                    class="flex items-center justify-center w-7 h-7 rounded-lg border border-gray-200 dark:border-slate-700 text-gray-400 hover:text-blue-600 hover:border-blue-300 dark:hover:text-blue-400 dark:hover:border-blue-600 transition-colors flex-shrink-0">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16"/></svg>
            </button>
        </div>

        {# Nav links #}
        <nav class="flex flex-col gap-0.5 px-3 flex-1">
            <a href="/" class="sidebar-link {% if request.url.path == '/' %}sidebar-link-active{% endif %}">
                <span>📅</span><span class="sidebar-label">Daily Digest</span>
            </a>

            {% if request.url.path.startswith('/youtube') %}
            <div id="youtubeNav" class="sidebar-link sidebar-link-active youtube-parent cursor-pointer">
                <span>🎬</span><span class="sidebar-label">YouTube</span>
                <span id="youtubeChevron" class="text-xs text-gray-400 ml-auto flex-shrink-0">▸</span>
            </div>
            <div id="youtubeSubnav" class="hidden flex-col ml-4 border-l-2 border-gray-200 dark:border-slate-700 py-0.5">
                {% block sidebar_subnav %}{% endblock %}
            </div>
            {% else %}
            <a href="/youtube" class="sidebar-link">
                <span>🎬</span><span class="sidebar-label">YouTube</span>
            </a>
            {% endif %}

            <a href="/history" class="sidebar-link {% if request.url.path.startswith('/history') %}sidebar-link-active{% endif %}">
                <span>📚</span><span class="sidebar-label">History</span>
            </a>
            <a href="/sources" class="sidebar-link {% if request.url.path.startswith('/sources') %}sidebar-link-active{% endif %}">
                <span>📡</span><span class="sidebar-label">Sources</span>
            </a>
        </nav>

        {# Footer group #}
        <div class="border-t border-gray-100 dark:border-slate-800 px-3 py-2 flex flex-col gap-0.5">
            <a href="/settings" class="sidebar-link {% if request.url.path.startswith('/settings') %}sidebar-link-active{% endif %}">
                <span>⚙️</span><span class="sidebar-label">Settings</span>
            </a>
            <button id="themeToggle" title="Toggle dark mode" aria-label="Toggle dark mode"
                    class="flex items-center gap-2.5 px-3 py-2 rounded-lg text-gray-500 hover:text-gray-900 hover:bg-gray-50 dark:hover:text-white dark:hover:bg-slate-800 transition-colors text-sm font-medium">
                <span class="w-5 text-center flex-shrink-0" id="themeIcon">☀️</span>
                <span class="sidebar-label" id="themeLabel">Light</span>
            </button>
        </div>
    </aside>

    {# ── Collapsed sidebar override styles ── #}
    <style>
        .sidebar-collapsed #sidebar { width: 64px; }
        .sidebar-collapsed #sidebar .sidebar-label { display: none; }
        .sidebar-collapsed #sidebar nav .sidebar-link { justify-content: center; padding-left: 0.25rem; padding-right: 0.25rem; }
        .sidebar-collapsed #sidebar .sidebar-brand-row .font-bold { display: none; }
        .sidebar-collapsed #sidebar #youtubeSubnav { display: none !important; }
        .sidebar-collapsed #themeToggle { justify-content: center; }
    </style>

    {# ── Mobile Top Bar ── #}
    <header class="sticky top-0 z-30 flex items-center h-14 px-4 bg-white dark:bg-slate-900 border-b border-gray-200 dark:border-slate-800 md:hidden">
        <button id="mobileMenuBtn" title="Open menu" aria-label="Open menu"
                class="flex items-center justify-center w-9 h-9 rounded-lg text-gray-500 hover:text-blue-600 hover:bg-gray-50 dark:hover:text-blue-400 dark:hover:bg-slate-800 transition-colors mr-3">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16"/></svg>
        </button>
        <a href="/" class="font-bold text-base text-gray-900 dark:text-white">📰 Media Hub</a>
        <button id="mobileThemeToggle" title="Toggle dark mode" aria-label="Toggle dark mode"
                class="ml-auto flex items-center justify-center w-9 h-9 rounded-lg text-gray-500 hover:text-blue-600 hover:bg-gray-50 dark:hover:text-blue-400 dark:hover:bg-slate-800 transition-colors">
            <span id="mobileThemeIcon">☀️</span>
        </button>
    </header>

    {# ── Mobile Slide-over Drawer ── #}
    <div id="mobileDrawerOverlay" class="fixed inset-0 z-40 bg-black/50 opacity-0 pointer-events-none transition-opacity duration-200 md:hidden"></div>
    <aside id="mobileDrawer" class="fixed inset-y-0 left-0 z-50 w-72 bg-white dark:bg-slate-900 border-r border-gray-200 dark:border-slate-800 flex flex-col transform -translate-x-full transition-transform duration-200 md:hidden">
        <div class="flex items-center justify-between px-4 py-4 border-b border-gray-100 dark:border-slate-800">
            <span class="font-bold text-base text-gray-900 dark:text-white">📰 Media Hub</span>
            <button id="mobileDrawerClose" title="Close menu" aria-label="Close menu"
                    class="flex items-center justify-center w-8 h-8 rounded-lg text-gray-400 hover:text-gray-900 hover:bg-gray-50 dark:hover:text-white dark:hover:bg-slate-800 transition-colors">
                <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
            </button>
        </div>
        <nav class="flex flex-col gap-0.5 px-3 py-3 flex-1">
            <a href="/" class="sidebar-link {% if request.url.path == '/' %}sidebar-link-active{% endif %}">
                <span>📅</span><span>Daily Digest</span>
            </a>
            <a href="/youtube" class="sidebar-link {% if request.url.path.startswith('/youtube') %}sidebar-link-active{% endif %}">
                <span>🎬</span><span>YouTube</span>
            </a>
            <a href="/history" class="sidebar-link {% if request.url.path.startswith('/history') %}sidebar-link-active{% endif %}">
                <span>📚</span><span>History</span>
            </a>
            <a href="/sources" class="sidebar-link {% if request.url.path.startswith('/sources') %}sidebar-link-active{% endif %}">
                <span>📡</span><span>Sources</span>
            </a>
            <a href="/settings" class="sidebar-link {% if request.url.path.startswith('/settings') %}sidebar-link-active{% endif %}">
                <span>⚙️</span><span>Settings</span>
            </a>
        </nav>
    </aside>

    {# ── Main Content ── #}
    <main class="md:ml-60 transition-[margin] duration-200" id="mainContent">
        <div class="max-w-3xl mx-auto px-4 sm:px-6 py-6 sm:py-8 pb-16">
            {% block content %}{% endblock %}
        </div>
        <footer class="text-center py-8 text-sm text-gray-400 dark:text-slate-500">
            Personal Media Intelligence Hub
        </footer>
    </main>

    {# ── Sidebar link styles (scoped to sidebar/drawer) ── #}
    <style>
        .sidebar-link {
            display: flex; align-items: center; gap: 0.625rem;
            padding: 0.625rem 0.75rem; border-radius: 0.5rem;
            font-size: 0.875rem; font-weight: 500; color: #737373;
            transition: all 0.15s; text-decoration: none; white-space: nowrap; overflow: hidden;
        }
        .sidebar-link:hover { color: #171717; background: #f9fafb; }
        .dark .sidebar-link:hover { color: #e2e8f0; background: rgba(30,41,59,0.8); }
        .sidebar-link-active { color: #2563eb; background: #eff6ff; }
        .dark .sidebar-link-active { color: #60a5fa; background: rgba(37,99,235,0.1); }
    </style>

    {# ── JavaScript: Sidebar toggle, theme, mobile drawer, YouTube subnav ── #}
    <script>
    (function() {
        // ── Theme ──
        const html = document.documentElement;
        function updateThemeUI() {
            const isDark = html.getAttribute('data-theme') === 'dark';
            const desktopIcon = document.getElementById('themeIcon');
            const desktopLabel = document.getElementById('themeLabel');
            const mobileIcon = document.getElementById('mobileThemeIcon');
            if (desktopIcon) desktopIcon.textContent = isDark ? '🌙' : '☀️';
            if (desktopLabel) desktopLabel.textContent = isDark ? 'Dark' : 'Light';
            if (mobileIcon) mobileIcon.textContent = isDark ? '🌙' : '☀️';
        }
        updateThemeUI();

        function toggleTheme() {
            const isDark = html.getAttribute('data-theme') === 'dark';
            if (isDark) { html.removeAttribute('data-theme'); localStorage.setItem('theme', 'light'); }
            else { html.setAttribute('data-theme', 'dark'); localStorage.setItem('theme', 'dark'); }
            updateThemeUI();
        }

        document.getElementById('themeToggle').addEventListener('click', toggleTheme);
        document.getElementById('mobileThemeToggle').addEventListener('click', toggleTheme);

        // ── Desktop sidebar collapse ──
        const mainContent = document.getElementById('mainContent');
        const sidebarToggle = document.getElementById('sidebarToggle');
        const savedCollapsed = localStorage.getItem('sidebar-collapsed') === 'true';
        if (savedCollapsed) { mainContent.classList.add('sidebar-collapsed'); }

        sidebarToggle.addEventListener('click', () => {
            mainContent.classList.toggle('sidebar-collapsed');
            localStorage.setItem('sidebar-collapsed', mainContent.classList.contains('sidebar-collapsed'));
        });

        // Also adjust main margin when collapsed
        const styleSheet = document.createElement('style');
        styleSheet.textContent = '.sidebar-collapsed #mainContent { margin-left: 64px; }';
        document.head.appendChild(styleSheet);

        // ── Mobile drawer ──
        const drawer = document.getElementById('mobileDrawer');
        const overlay = document.getElementById('mobileDrawerOverlay');
        function openDrawer() {
            drawer.classList.remove('-translate-x-full');
            overlay.classList.remove('opacity-0', 'pointer-events-none');
        }
        function closeDrawer() {
            drawer.classList.add('-translate-x-full');
            overlay.classList.add('opacity-0', 'pointer-events-none');
        }
        document.getElementById('mobileMenuBtn').addEventListener('click', openDrawer);
        document.getElementById('mobileDrawerClose').addEventListener('click', closeDrawer);
        overlay.addEventListener('click', closeDrawer);

        // ── YouTube subnav ──
        const ytNav = document.getElementById('youtubeNav');
        const ytSubnav = document.getElementById('youtubeSubnav');
        const ytChevron = document.getElementById('youtubeChevron');
        if (ytNav && ytSubnav && ytChevron) {
            const STORAGE_KEY = 'youtube-subnav-expanded';
            function expand() {
                ytSubnav.classList.remove('hidden');
                ytChevron.textContent = '▾';
            }
            function collapse() {
                ytSubnav.classList.add('hidden');
                ytChevron.textContent = '▸';
            }
            const saved = localStorage.getItem(STORAGE_KEY);
            if (saved !== 'false') expand();
            ytNav.addEventListener('click', () => {
                if (ytSubnav.classList.contains('hidden')) { expand(); localStorage.setItem(STORAGE_KEY, 'true'); }
                else { collapse(); localStorage.setItem(STORAGE_KEY, 'false'); }
            });
        }
    })();
    </script>
</body>
```

- [ ] **Step 2: Verify the layout renders**

Start the Flask/FastAPI dev server and visit the homepage. You should see:
- Desktop: sidebar on left, main content area to the right, Inter font applied
- Dark mode toggle works (clicking changes theme)
- Sidebar collapse toggle works
- Mobile (≤768px): top bar with hamburger, clicking opens slide-over drawer

- [ ] **Step 3: Commit**

```bash
git add app/web/templates/base.html
git commit -m "feat: convert base.html layout to Tailwind with mobile drawer"
```

---

### Task 3: Convert Daily Digest Page (index.html)

**Files:**
- Modify: `app/web/templates/index.html`

**Interfaces:**
- Consumes: Tailwind-styled base.html from Task 2
- Uses: Jinja2 variables `today_pretty`, `prev_date`, `next_date`, `last_scrape`, `digest`, `digest_articles`, `recent_articles`, `scrape_time`

- [ ] **Step 1: Write the new index.html**

Replace entire content of `app/web/templates/index.html`:

```html
{% extends "base.html" %}
{% block title %}Daily Digest — {{ today_pretty }}{% endblock %}

{% block content %}

{# ── Date Navigation ── #}
<div class="flex items-center justify-between mb-8">
    {% if prev_date %}
    <a href="/digest/{{ prev_date }}" class="inline-flex items-center gap-1.5 rounded-full px-4 py-1.5 border border-gray-200 dark:border-slate-700 text-sm text-gray-500 hover:text-blue-600 hover:border-blue-300 dark:hover:text-blue-400 dark:hover:border-blue-600 transition-colors">
        ← {{ prev_date }}
    </a>
    {% else %}
    <span class="inline-flex items-center gap-1.5 rounded-full px-4 py-1.5 border border-gray-100 dark:border-slate-800 text-sm text-gray-300 dark:text-slate-600 pointer-events-none opacity-40">←</span>
    {% endif %}

    <h1 class="text-2xl font-bold text-gray-900 dark:text-white">📅 {{ today_pretty }}</h1>

    {% if next_date %}
    <a href="/digest/{{ next_date }}" class="inline-flex items-center gap-1.5 rounded-full px-4 py-1.5 border border-gray-200 dark:border-slate-700 text-sm text-gray-500 hover:text-blue-600 hover:border-blue-300 dark:hover:text-blue-400 dark:hover:border-blue-600 transition-colors">
        {{ next_date }} →
    </a>
    {% else %}
    <span class="inline-flex items-center gap-1.5 rounded-full px-4 py-1.5 border border-gray-100 dark:border-slate-800 text-sm text-gray-300 dark:text-slate-600 pointer-events-none opacity-40">→</span>
    {% endif %}
</div>

{# ── Status Strip ── #}
{% if last_scrape %}
<div class="flex flex-wrap items-center gap-2 mb-6">
    <span class="inline-flex items-center gap-1 rounded-full px-3 py-1 bg-gray-50 dark:bg-slate-800 text-xs text-gray-500 dark:text-slate-400">
        🕐 <strong class="font-medium text-gray-700 dark:text-slate-300">Last scrape:</strong> {{ last_scrape.started_at[:16] }}
    </span>
    <span class="inline-flex items-center gap-1 rounded-full px-3 py-1 bg-gray-50 dark:bg-slate-800 text-xs text-gray-500 dark:text-slate-400">
        📰 <strong class="font-medium text-gray-700 dark:text-slate-300">{{ last_scrape.articles_new }}</strong> new
    </span>
    <span class="inline-flex items-center gap-1 rounded-full px-3 py-1 bg-gray-50 dark:bg-slate-800 text-xs text-gray-500 dark:text-slate-400">
        ✅ <strong class="font-medium text-gray-700 dark:text-slate-300">{{ last_scrape.feeds_success }}/{{ last_scrape.feeds_total }}</strong> feeds
    </span>
    <span class="inline-flex items-center gap-1 rounded-full px-3 py-1 bg-gray-50 dark:bg-slate-800 text-xs text-gray-500 dark:text-slate-400">
        ⏰ Next: <strong class="font-medium text-gray-700 dark:text-slate-300">{{ scrape_time }} IST</strong>
    </span>
    {% if digest %}
    <span class="inline-flex items-center gap-1.5 rounded-full px-3 py-1 bg-green-50 dark:bg-green-950 text-xs text-green-700 dark:text-green-400 font-medium">
        <span class="w-1.5 h-1.5 rounded-full bg-green-500"></span> Digest ready
    </span>
    {% else %}
    <span class="inline-flex items-center gap-1.5 rounded-full px-3 py-1 bg-amber-50 dark:bg-amber-950 text-xs text-amber-700 dark:text-amber-400 font-medium">
        <span class="w-1.5 h-1.5 rounded-full bg-amber-500"></span> Pending
    </span>
    {% endif %}
</div>
{% endif %}

{# ── Digest Content ── #}
{% if digest %}
<article class="rounded-xl shadow-sm border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 sm:p-8 mb-6">
    <div class="font-serif text-base leading-relaxed text-gray-800 dark:text-gray-200 digest-body">
        {{ digest.summary_text | markdown | safe }}
    </div>

    <footer class="mt-6 pt-4 border-t border-gray-100 dark:border-slate-800 text-sm text-gray-400 dark:text-slate-500">
        {{ digest.article_count }} articles from {{ digest.source_count }} sources
    </footer>
</article>

{# ── Articles in digest ── #}
{% if digest_articles %}
<details class="mb-6">
    <summary class="cursor-pointer text-sm font-medium text-gray-500 hover:text-blue-600 dark:text-slate-400 dark:hover:text-blue-400 transition-colors py-1 select-none">
        Articles in this digest ({{ digest_articles|length }})
    </summary>
    <div class="mt-3 rounded-xl border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 p-4 sm:p-5">
    {% for da in digest_articles %}
        <div class="flex items-start gap-3 py-2">
            <a href="/article/{{ da.id }}" class="text-sm text-blue-600 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300 font-medium flex-1">{{ da.title }}</a>
            {% if da.source_category %}
            <span class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap
                {% if da.source_category|lower == 'markets' %}bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-300
                {% elif da.source_category|lower == 'politics' %}bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300
                {% elif da.source_category|lower == 'world' %}bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300
                {% elif da.source_category|lower == 'tech' %}bg-indigo-100 text-indigo-800 dark:bg-indigo-900 dark:text-indigo-300
                {% else %}bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300{% endif %}
            ">{{ da.source_category }}</span>
            {% endif %}
        </div>
    {% endfor %}
    </div>
</details>
{% endif %}

{# ── Empty State ── #}
{% else %}
<div class="flex flex-col items-center justify-center py-16 px-4 text-center">
    <div class="text-6xl mb-4">📭</div>
    <h3 class="text-lg font-semibold text-gray-900 dark:text-white mb-2">No digest available for {{ today_pretty }}</h3>
    <p class="text-gray-500 dark:text-slate-400">The daily scrape runs at <strong class="font-medium text-gray-700 dark:text-slate-300">{{ scrape_time }} IST</strong>.</p>
    {% if recent_articles %}
    <p class="text-sm text-gray-400 dark:text-slate-500 mt-3">Showing recent articles below.</p>
    {% else %}
    <p class="text-sm text-gray-400 dark:text-slate-500 mt-2">Check back after the scheduled scrape, or visit <a href="/history" class="text-blue-600 hover:underline dark:text-blue-400">history</a> for past digests.</p>
    {% endif %}
</div>

{% if recent_articles %}
<div class="mt-6">
    <h3 class="text-lg font-semibold text-gray-900 dark:text-white mb-4">📰 Recent Articles</h3>
    <div class="rounded-xl border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 p-4 sm:p-5">
    {% for article in recent_articles %}
        <div class="flex items-start gap-3 py-2">
            <a href="/article/{{ article.id }}" class="text-sm text-blue-600 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300 font-medium flex-1">{{ article.title }}</a>
            <span class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300 whitespace-nowrap">{{ article.source_name or 'Unknown' }}</span>
        </div>
    {% endfor %}
    </div>
</div>
{% endif %}

{% endif %}

{% endblock %}
```

- [ ] **Step 2: Test the digest page**

Visit `/` (or `/digest/YYYY-MM-DD`). Verify:
- Date navigation arrows work, disabled state shows faded
- Status strip shows as pill row
- Digest card renders with serif text, proper spacing
- Articles in digest expandable section works
- Empty state looks clean

- [ ] **Step 3: Commit**

```bash
git add app/web/templates/index.html
git commit -m "feat: convert daily digest page to Tailwind"
```

---

### Task 4: Convert Article Page (article.html)

**Files:**
- Modify: `app/web/templates/article.html`

- [ ] **Step 1: Write the new article.html**

Replace entire content:

```html
{% extends "base.html" %}
{% block title %}{{ article.title }}{% endblock %}

{% block content %}

{# ── Breadcrumb ── #}
<nav class="mb-4 text-sm text-gray-400 dark:text-slate-500">
    <a href="/" class="hover:text-blue-600 dark:hover:text-blue-400 transition-colors">Today's Digest</a>
    <span class="mx-1.5 text-gray-300 dark:text-slate-600">›</span>
    <span class="text-gray-500 dark:text-slate-400">Article</span>
</nav>

{# ── Header ── #}
<header class="mb-6">
    <h1 class="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-white leading-tight">{{ article.title }}</h1>
    <div class="flex flex-wrap items-center gap-2 mt-3 text-sm text-gray-500 dark:text-slate-400">
        {% if article.author %}<span>✍️ {{ article.author }}</span>{% endif %}
        {% if article.published_at %}
        <span class="text-gray-300 dark:text-slate-600">·</span>
        <span>📅 {{ article.published_at[:10] }}</span>
        {% endif %}
        {% if article.fetched_at %}
        <span class="text-gray-300 dark:text-slate-600">·</span>
        <span>Fetched {{ article.fetched_at[:10] }}</span>
        {% endif %}
        {% if article.chunk_count > 1 %}
        <span class="text-gray-300 dark:text-slate-600">·</span>
        <span class="italic">{{ article.chunk_count }} chunks</span>
        {% endif %}
    </div>
</header>

{# ── Summary ── #}
{% if article.summary_text %}
<div class="rounded-r-xl border-l-4 border-blue-500 bg-blue-50/50 dark:bg-blue-950/20 p-5 sm:p-6 mb-6">
    <h3 class="text-base font-semibold text-gray-900 dark:text-white mb-3">📝 Summary</h3>
    <div class="font-serif text-base leading-relaxed text-gray-800 dark:text-gray-200">
        {{ article.summary_text | markdown | safe }}
    </div>
</div>
{% elif article.status == 'summarizing' %}
<div class="rounded-xl border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 p-8 text-center mb-6">
    <p class="text-gray-500 dark:text-slate-400">⏳ Summarization in progress...</p>
</div>
{% elif article.status == 'failed' %}
<div class="rounded-r-xl border-l-4 border-red-500 bg-red-50 dark:bg-red-950/20 p-4 mb-6 text-red-700 dark:text-red-300">
    <p class="font-semibold">❌ Summarization failed</p>
    {% if article.error_message %}<p class="text-sm mt-1 opacity-80">{{ article.error_message }}</p>{% endif %}
</div>
{% else %}
<div class="rounded-xl border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 p-8 text-center mb-6">
    <p class="text-gray-500 dark:text-slate-400">⏳ Awaiting summarization...</p>
</div>
{% endif %}

{# ── Original Text ── #}
{% if article.raw_text %}
<details class="mb-6">
    <summary class="cursor-pointer text-sm font-medium text-gray-500 hover:text-blue-600 dark:text-slate-400 dark:hover:text-blue-400 transition-colors py-1">
        📄 View original text ({{ article.raw_text.split()|length }} words)
    </summary>
    <div class="mt-3 max-h-96 overflow-y-auto rounded-lg border border-gray-200 dark:border-slate-700 bg-gray-50 dark:bg-slate-800 p-4 text-sm font-serif leading-relaxed text-gray-700 dark:text-slate-300">
        {% for paragraph in article.raw_text.split('\n\n') %}
            <p class="mb-3 last:mb-0">{{ paragraph }}</p>
        {% endfor %}
    </div>
</details>
{% endif %}

{# ── Footer Links ── #}
<div class="flex flex-wrap gap-3 mt-8">
    <a href="{{ article.url }}" target="_blank" rel="noopener" class="inline-flex items-center gap-2 rounded-lg bg-blue-600 text-white px-4 py-2 text-sm font-medium hover:bg-blue-700 transition-colors active:scale-95">
        🔗 Read original article
    </a>
    {% if article.fetched_at %}
    <a href="/digest/{{ article.fetched_at[:10] }}" class="inline-flex items-center gap-2 rounded-lg border border-gray-200 dark:border-slate-700 text-gray-600 dark:text-slate-400 px-4 py-2 text-sm font-medium hover:border-blue-300 hover:text-blue-600 dark:hover:text-blue-400 transition-colors">
        📅 View digest for {{ article.fetched_at[:10] }}
    </a>
    {% endif %}
</div>

{% endblock %}
```

- [ ] **Step 2: Verify article page**

Visit an article page. Check:
- Breadcrumb renders
- Title and meta row
- Summary card with blue left border
- Error states (summarizing, failed, awaiting)
- Raw text expandable section
- Action buttons

- [ ] **Step 3: Commit**

```bash
git add app/web/templates/article.html
git commit -m "feat: convert article page to Tailwind"
```

---

### Task 5: Convert History Page (history.html)

**Files:**
- Modify: `app/web/templates/history.html`

- [ ] **Step 1: Write the new history.html**

```html
{% extends "base.html" %}
{% block title %}Digest History{% endblock %}

{% block content %}

<h1 class="text-2xl font-bold text-gray-900 dark:text-white mb-1">📚 Digest History</h1>
<p class="text-sm text-gray-500 dark:text-slate-400 mb-6">Browse past daily digests</p>

{% if years %}
<div class="flex flex-wrap gap-1.5 mb-4">
    {% for y in years %}
    <a href="/history?year={{ y }}" class="inline-flex rounded-full px-3.5 py-1.5 text-sm font-medium transition-colors
        {% if y == selected_year %}bg-blue-600 text-white{% else %}text-gray-500 hover:text-blue-600 border border-gray-200 dark:border-slate-700 dark:text-slate-400 dark:hover:text-blue-400{% endif %}">
        {{ y }}
    </a>
    {% endfor %}
</div>

<div class="mb-6">
    <select onchange="const val=this.value;location.href=val?'/history?year={{ selected_year }}&month='+val:'/history?year={{ selected_year }}'"
            class="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-gray-700 dark:text-slate-300 text-sm py-2 px-3 focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
        <option value="">All months</option>
        {% for m in range(1, 13) %}
        <option value="{{ m }}" {% if selected_month == m %}selected{% endif %}>
            {{ ['January','February','March','April','May','June','July','August','September','October','November','December'][m-1] }}
        </option>
        {% endfor %}
    </select>
</div>
{% endif %}

{% if digests %}
<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
    {% for d in digests %}
    <a href="/digest/{{ d.date }}" class="block rounded-xl shadow-sm border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 p-5 hover:shadow-md hover:-translate-y-0.5 transition-all no-underline text-gray-900 dark:text-white">
        <div class="text-xs text-gray-400 dark:text-slate-500 mb-1">{{ d.date }}</div>
        <div class="font-semibold text-gray-900 dark:text-white mb-1.5">{{ d.title or d.date }}</div>
        <div class="text-xs text-gray-500 dark:text-slate-400 mb-2">{{ d.article_count }} articles · {{ d.source_count }} sources</div>
        {% if d.summary_text %}
        <div class="text-sm text-gray-500 dark:text-slate-400 line-clamp-3 leading-relaxed">{{ d.summary_text[:200] }}…</div>
        {% endif %}
    </a>
    {% endfor %}
</div>

{% elif years %}
<div class="flex flex-col items-center justify-center py-12 text-center">
    <div class="text-5xl mb-3">📭</div>
    <h3 class="text-lg font-semibold text-gray-900 dark:text-white mb-1">No digests found for {{ selected_year }}{% if selected_month %} — {{ ['January','February','March','April','May','June','July','August','September','October','November','December'][selected_month-1] }}{% endif %}</h3>
    <p class="text-sm text-gray-500 dark:text-slate-400">Try a different year or month.</p>
</div>

{% else %}
<div class="flex flex-col items-center justify-center py-16 text-center">
    <div class="text-6xl mb-4">📚</div>
    <h3 class="text-lg font-semibold text-gray-900 dark:text-white mb-2">No digests yet</h3>
    <p class="text-gray-500 dark:text-slate-400">Once the scraper runs and summaries are generated, your digest history will appear here.</p>
</div>
{% endif %}

{% endblock %}
```

- [ ] **Step 2: Test history page**

Visit `/history`. Verify:
- Year pills render, active year highlighted
- Month dropdown works
- Card grid renders with hover lift
- Empty states render correctly

- [ ] **Step 3: Commit**

```bash
git add app/web/templates/history.html
git commit -m "feat: convert history page to Tailwind"
```

---

### Task 6: Convert YouTube Pages (youtube.html + youtube_history.html)

**Files:**
- Modify: `app/web/templates/youtube.html`
- Modify: `app/web/templates/youtube_history.html`

- [ ] **Step 1: Write the new youtube.html**

Replace entire content of `app/web/templates/youtube.html`:

```html
{% extends "base.html" %}
{% block title %}YouTube — {{ display_date_pretty }}{% endblock %}

{% block head_extra %}{% endblock %}

{# ── Channel list as sidebar subnav ── #}
{% block sidebar_subnav %}
{% if channels %}
{% set active_channels = channels | selectattr('is_active', 'equalto', 1) | list %}
{% set paused_channels = channels | selectattr('is_active', 'equalto', 0) | list %}
<a href="/youtube?date={{ display_date }}"
   class="flex items-center gap-2 px-2.5 py-1.5 text-xs rounded-md text-gray-500 hover:text-gray-900 dark:text-slate-400 dark:hover:text-white transition-colors {% if not selected_channel %}text-blue-600 dark:text-blue-400 font-semibold bg-blue-50 dark:bg-blue-950{% endif %}">
    All Channels
</a>
{% for ch in active_channels %}
<a href="/youtube?channel={{ ch.id }}&date={{ display_date }}"
   class="flex items-center gap-2 px-2.5 py-1.5 text-xs rounded-md text-gray-500 hover:text-gray-900 dark:text-slate-400 dark:hover:text-white transition-colors {% if selected_channel == ch.id %}text-blue-600 dark:text-blue-400 font-semibold bg-blue-50 dark:bg-blue-950{% endif %}"
   title="{{ ch.name }}">
    {{ ch.name }}
    {% set cnt = channel_counts.get(ch.id, 0) %}
    {% if cnt > 0 %}<span class="ml-auto text-[10px] font-semibold bg-blue-600 text-white rounded-full px-1.5 py-px leading-relaxed">{{ cnt }}</span>{% endif %}
</a>
{% endfor %}
{% if paused_channels %}
<div class="text-[10px] font-semibold uppercase tracking-wider text-gray-400 dark:text-slate-500 px-2.5 py-1.5">Paused</div>
{% for ch in paused_channels %}
<a href="/youtube?channel={{ ch.id }}&date={{ display_date }}"
   class="flex items-center gap-2 px-2.5 py-1.5 text-xs rounded-md text-gray-400 dark:text-slate-500 hover:text-gray-600 dark:hover:text-slate-300 transition-colors opacity-50 hover:opacity-75 {% if selected_channel == ch.id %}text-blue-600 dark:text-blue-400 font-semibold{% endif %}"
   title="{{ ch.name }}">
    {{ ch.name }}
</a>
{% endfor %}
{% endif %}
{% endif %}
{% endblock %}

{% block content %}

{# ── Mobile channel pills ── #}
{% if channels %}
{% set active_channels = channels | selectattr('is_active', 'equalto', 1) | list %}
{% set paused_channels = channels | selectattr('is_active', 'equalto', 0) | list %}
<div class="flex flex-wrap gap-1.5 mb-6 pb-4 border-b border-gray-100 dark:border-slate-800 md:hidden">
    <a href="/youtube?date={{ display_date }}"
       class="inline-flex rounded-full px-3 py-1 text-xs font-medium transition-colors {% if not selected_channel %}bg-blue-600 text-white{% else %}border border-gray-200 dark:border-slate-700 text-gray-500 dark:text-slate-400 hover:text-blue-600 dark:hover:text-blue-400{% endif %}">
        All
    </a>
    {% for ch in active_channels %}
    <a href="/youtube?channel={{ ch.id }}&date={{ display_date }}"
       class="inline-flex rounded-full px-3 py-1 text-xs font-medium transition-colors {% if selected_channel == ch.id %}bg-blue-600 text-white{% else %}border border-gray-200 dark:border-slate-700 text-gray-500 dark:text-slate-400 hover:text-blue-600 dark:hover:text-blue-400{% endif %}">
        {{ ch.name }}
        {% set cnt = channel_counts.get(ch.id, 0) %}
        {% if cnt > 0 %}<span class="ml-1 opacity-80">({{ cnt }})</span>{% endif %}
    </a>
    {% endfor %}
    {% for ch in paused_channels %}
    <a href="/youtube?channel={{ ch.id }}"
       class="inline-flex rounded-full px-3 py-1 text-xs font-medium border border-gray-100 dark:border-slate-800 text-gray-400 dark:text-slate-600 opacity-50">
        {{ ch.name }}
    </a>
    {% endfor %}
</div>
{% endif %}

{# ── Status Strip ── #}
{% if last_scrape %}
<div class="flex flex-wrap items-center gap-2 mb-6">
    <span class="inline-flex items-center gap-1 rounded-full px-3 py-1 bg-gray-50 dark:bg-slate-800 text-xs text-gray-500 dark:text-slate-400">
        🕐 <strong class="font-medium text-gray-700 dark:text-slate-300">Last scrape:</strong> {{ last_scrape.started_at[:16] }}
    </span>
    <span class="inline-flex items-center gap-1 rounded-full px-3 py-1 bg-gray-50 dark:bg-slate-800 text-xs text-gray-500 dark:text-slate-400">
        🎬 <strong class="font-medium text-gray-700 dark:text-slate-300">{{ channel_counts.values() | sum }}</strong> new videos
    </span>
</div>
{% endif %}

{# ── Date Navigation ── #}
<div class="flex items-center justify-between mb-8">
    {% if prev_date %}
    <a href="/youtube?date={{ prev_date }}{% if selected_channel %}&channel={{ selected_channel }}{% endif %}"
       class="inline-flex items-center gap-1.5 rounded-full px-4 py-1.5 border border-gray-200 dark:border-slate-700 text-sm text-gray-500 hover:text-blue-600 hover:border-blue-300 dark:hover:text-blue-400 dark:hover:border-blue-600 transition-colors">
        ← {{ prev_date }}
    </a>
    {% else %}
    <span class="inline-flex items-center gap-1.5 rounded-full px-4 py-1.5 border border-gray-100 dark:border-slate-800 text-sm text-gray-300 dark:text-slate-600 pointer-events-none opacity-40">←</span>
    {% endif %}

    <h1 class="text-2xl font-bold text-gray-900 dark:text-white">🎬 {{ display_date_pretty }}</h1>

    {% if next_date %}
    <a href="/youtube?date={{ next_date }}{% if selected_channel %}&channel={{ selected_channel }}{% endif %}"
       class="inline-flex items-center gap-1.5 rounded-full px-4 py-1.5 border border-gray-200 dark:border-slate-700 text-sm text-gray-500 hover:text-blue-600 hover:border-blue-300 dark:hover:text-blue-400 dark:hover:border-blue-600 transition-colors">
        {{ next_date }} →
    </a>
    {% else %}
    <span class="inline-flex items-center gap-1.5 rounded-full px-4 py-1.5 border border-gray-100 dark:border-slate-800 text-sm text-gray-300 dark:text-slate-600 pointer-events-none opacity-40">→</span>
    {% endif %}
</div>

{# ── Video Card macro ── #}
{% macro video_card(video, show_source=True, truncate=True) %}
<article class="rounded-xl shadow-sm border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 p-5 hover:shadow-md transition-shadow">
    <div class="flex items-start justify-between gap-3">
        <div class="flex-1 min-w-0">
            <a href="/article/{{ video.id }}" class="font-semibold text-gray-900 dark:text-white hover:text-blue-600 dark:hover:text-blue-400 transition-colors leading-snug">
                {{ video.title }}
            </a>
            {% if show_source and video.source_name %}
            <span class="text-xs text-gray-400 dark:text-slate-500 ml-2">{{ video.source_name }}</span>
            {% endif %}
        </div>
        <a href="{{ video.url }}" target="_blank" rel="noopener"
           class="inline-flex items-center gap-1 rounded-lg bg-red-600 text-white px-3 py-1.5 text-xs font-medium hover:bg-red-700 transition-colors active:scale-95 flex-shrink-0">
            ▶ Watch
        </a>
    </div>
    {% if video.summary_text %}
    <div class="mt-2 text-sm font-serif leading-relaxed text-gray-600 dark:text-slate-400">
        {% if truncate %}
        {{ video.summary_text[:400] }}{% if video.summary_text|length > 400 %}... <a href="/article/{{ video.id }}" class="text-blue-600 dark:text-blue-400 hover:underline">read more</a>{% endif %}
        {% else %}
        {{ video.summary_text | markdown | safe }}
        {% endif %}
    </div>
    {% endif %}
    <div class="mt-2 text-xs text-gray-400 dark:text-slate-500">
        {{ video.published_at[:10] if video.published_at else '' }}
        {% if video.duration_seconds %} &middot; {{ (video.duration_seconds // 60) | int }} min{% endif %}
    </div>
</article>
{% endmacro %}

{# ── State 1: No channels ── #}
{% if not channels %}
<div class="flex flex-col items-center justify-center py-16 text-center">
    <div class="text-6xl mb-4">🎬</div>
    <h3 class="text-lg font-semibold text-gray-900 dark:text-white mb-2">No YouTube channels yet</h3>
    <p class="text-gray-500 dark:text-slate-400 mb-3">You're not following any YouTube channels.</p>
    <p><a href="/settings" class="text-blue-600 hover:underline dark:text-blue-400 font-medium">Add your first channel →</a></p>
</div>

{# ── State 2: Per-channel, no videos today ── #}
{% elif selected_channel and not digest_videos %}
<div class="flex flex-col items-center justify-center py-12 text-center">
    <div class="text-5xl mb-3">📭</div>
    <h3 class="text-lg font-semibold text-gray-900 dark:text-white mb-1">
        {% for ch in channels if ch.id == selected_channel %}{{ ch.name }}{% endfor %} hasn't posted today.
    </h3>
    <p class="text-sm text-gray-500 dark:text-slate-400">The daily scrape runs at <strong>{{ scrape_time }} IST</strong>.</p>
</div>

{% if recent_videos %}
<div class="mt-8">
    <h3 class="text-lg font-semibold text-gray-900 dark:text-white mb-4">Recent videos</h3>
    <div class="flex flex-col gap-3">
    {% for rv in recent_videos %}
        {{ video_card(rv) }}
    {% endfor %}
    </div>
</div>
{% endif %}

{# ── State 2b: Per-channel, videos today ── #}
{% elif selected_channel and digest_videos %}
<div class="mt-4">
    <h3 class="text-lg font-semibold text-gray-900 dark:text-white mb-4">
        {% for ch in channels if ch.id == selected_channel %}{{ ch.name }}{% endfor %}
        — {{ digest_videos|length }} video{{ 's' if digest_videos|length != 1 else '' }}
    </h3>
    <div class="flex flex-col gap-3">
    {% for video in digest_videos %}
        {{ video_card(video, show_source=False, truncate=False) }}
    {% endfor %}
    </div>
</div>

{# ── State 3: No digest (all channels) ── #}
{% elif not digest and not selected_channel %}
<div class="flex flex-col items-center justify-center py-12 text-center">
    <div class="text-5xl mb-3">📭</div>
    <h3 class="text-lg font-semibold text-gray-900 dark:text-white mb-1">No videos today</h3>
    <p class="text-sm text-gray-500 dark:text-slate-400">The daily scrape runs at <strong>{{ scrape_time }} IST</strong>.</p>
    {% if channels %}
    <p class="text-xs text-gray-400 dark:text-slate-500 mt-1">Following {{ active_channels|length }} channel{{ 's' if active_channels|length != 1 else '' }}.</p>
    {% endif %}
</div>

{% if recent_videos %}
<div class="mt-8">
    <h3 class="text-lg font-semibold text-gray-900 dark:text-white mb-4">Recent videos</h3>
    <div class="flex flex-col gap-3">
    {% for rv in recent_videos %}
        {{ video_card(rv) }}
    {% endfor %}
    </div>
</div>
{% endif %}

{# ── State 4: Digest exists ── #}
{% else %}
<article class="rounded-xl shadow-sm border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 sm:p-8 mb-6">
    <div class="font-serif text-base leading-relaxed text-gray-800 dark:text-gray-200">
        {{ digest.summary_text | markdown | safe }}
    </div>
    <footer class="mt-6 pt-4 border-t border-gray-100 dark:border-slate-800 text-sm text-gray-400 dark:text-slate-500">
        {{ digest.video_count }} videos from {{ digest.channel_count }} channel{{ 's' if digest.channel_count != 1 else '' }}
    </footer>
</article>

{% if digest_videos %}
<div class="mb-6">
    <button id="footnotesToggle" aria-expanded="false"
            class="inline-flex items-center gap-2 rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-4 py-2 text-sm font-medium text-gray-700 dark:text-slate-300 hover:border-blue-300 hover:text-blue-600 dark:hover:text-blue-400 transition-colors">
        <span id="footnotesArrow" class="text-xs transition-transform">▶</span>
        Videos in this digest ({{ digest_videos|length }})
    </button>
    <div id="videoFootnotes" class="hidden mt-3 flex flex-col gap-1.5">
        {% for video in digest_videos %}
        <div class="rounded-lg border border-gray-200 dark:border-slate-700 overflow-hidden" id="fn-{{ loop.index }}">
            <button class="flex items-center gap-2.5 w-full px-4 py-3 bg-white dark:bg-slate-900 hover:bg-gray-50 dark:hover:bg-slate-800 transition-colors text-left cursor-pointer border-none text-sm"
                    onclick="toggleFootnote('fn-{{ loop.index }}')" aria-expanded="false">
                <span class="font-bold text-xs text-blue-600 dark:text-blue-400 flex-shrink-0">[{{ video.inclusion_order }}]</span>
                <span class="flex-1 font-medium text-gray-900 dark:text-white truncate">{{ video.title }}</span>
                <span class="text-xs text-gray-400 dark:text-slate-500 flex-shrink-0 hidden sm:flex items-center gap-2">
                    <span>{{ video.source_name }}</span>
                    {% if video.duration_seconds %}<span>{{ (video.duration_seconds // 60) | int }} min</span>{% endif %}
                </span>
                <span class="footnote-expand-icon text-xs text-gray-400 flex-shrink-0 transition-transform">▸</span>
            </button>
            <div class="hidden px-4 py-4 border-t border-gray-100 dark:border-slate-700 bg-gray-50 dark:bg-slate-800">
                <div class="font-serif text-sm leading-relaxed text-gray-700 dark:text-slate-300 mb-3">
                    {{ video.summary_text | markdown | safe }}
                </div>
                <a href="{{ video.url }}" target="_blank" rel="noopener"
                   class="inline-flex items-center gap-1 rounded-lg bg-red-600 text-white px-3 py-1 text-xs font-medium hover:bg-red-700 transition-colors">
                    ▶ Watch
                </a>
            </div>
        </div>
        {% endfor %}
    </div>
</div>
{% endif %}

{% endif %}

{# ── Footnotes JS ── #}
<script>
(function() {
    const ftToggle = document.getElementById('footnotesToggle');
    const ftContainer = document.getElementById('videoFootnotes');
    const ftArrow = document.getElementById('footnotesArrow');
    if (ftToggle && ftContainer) {
        ftToggle.addEventListener('click', () => {
            const isOpen = !ftContainer.classList.contains('hidden');
            ftContainer.classList.toggle('hidden', isOpen);
            ftToggle.setAttribute('aria-expanded', String(!isOpen));
            ftArrow.textContent = isOpen ? '▶' : '▼';
        });
    }

    window.toggleFootnote = function(fnId) {
        const fn = document.getElementById(fnId);
        if (!fn) return;
        const detail = fn.querySelector(':scope > div:last-child');
        const row = fn.querySelector('button');
        const icon = fn.querySelector('.footnote-expand-icon');
        if (!detail || !row) return;
        const isOpen = !detail.classList.contains('hidden');
        detail.classList.toggle('hidden', isOpen);
        row.setAttribute('aria-expanded', String(!isOpen));
        if (icon) icon.textContent = isOpen ? '▸' : '▾';
    };
})();
</script>

{% endblock %}
```

- [ ] **Step 2: Write the new youtube_history.html**

Replace entire content:

```html
{% extends "base.html" %}
{% block title %}YouTube History{% endblock %}

{% block content %}
<h1 class="text-2xl font-bold text-gray-900 dark:text-white mb-1">🎬 YouTube Digest History</h1>
<p class="text-sm text-gray-500 dark:text-slate-400 mb-6">Browse past YouTube digests</p>

<div class="flex flex-wrap gap-1.5 mb-4">
{% for y in years %}
<a href="/youtube/history?year={{ y }}" class="inline-flex rounded-full px-3.5 py-1.5 text-sm font-medium transition-colors
    {% if y == selected_year %}bg-blue-600 text-white{% else %}text-gray-500 hover:text-blue-600 border border-gray-200 dark:border-slate-700 dark:text-slate-400 dark:hover:text-blue-400{% endif %}">
    {{ y }}
</a>
{% endfor %}
</div>

<div class="mb-6">
    <select onchange="const m=this.value;location.href=m?'/youtube/history?year={{ selected_year }}&month='+m:'/youtube/history?year={{ selected_year }}'"
            class="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-gray-700 dark:text-slate-300 text-sm py-2 px-3 focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
        <option value="">All months</option>
        {% for m in range(1,13) %}
        <option value="{{ m }}" {% if selected_month == m %}selected{% endif %}>{{ '%02d'|format(m) }}</option>
        {% endfor %}
    </select>
</div>

{% if digests %}
<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
{% for d in digests %}
<a href="/youtube?date={{ d.date }}" class="block rounded-xl shadow-sm border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 p-5 hover:shadow-md hover:-translate-y-0.5 transition-all no-underline">
    <div class="text-xs text-gray-400 dark:text-slate-500 mb-1">{{ d.date }}</div>
    <div class="font-semibold text-gray-900 dark:text-white mb-1.5">{{ d.title or d.date }}</div>
    <div class="text-xs text-gray-500 dark:text-slate-400">{{ d.video_count }} videos · {{ d.channel_count }} channels</div>
</a>
{% endfor %}
</div>
{% else %}
<div class="flex flex-col items-center justify-center py-16 text-center">
    <div class="text-5xl mb-3">📭</div>
    <h3 class="text-lg font-semibold text-gray-900 dark:text-white">No YouTube digests for this period</h3>
</div>
{% endif %}

{% endblock %}
```

- [ ] **Step 3: Test YouTube pages**

Visit `/youtube`. Verify:
- Channel subnav in sidebar renders and toggles
- Mobile channel pills appear on narrow screens
- Status strip and date nav
- All 4 states (no channels, per-channel empty, all-channel empty, digest exists)
- Video footnotes expand/collapse
- Watch buttons
- YouTube history page renders year tabs + card grid

- [ ] **Step 4: Commit**

```bash
git add app/web/templates/youtube.html app/web/templates/youtube_history.html
git commit -m "feat: convert YouTube pages to Tailwind"
```

---

### Task 7: Convert Sources Page (sources.html)

**Files:**
- Modify: `app/web/templates/sources.html`

- [ ] **Step 1: Write the new sources.html**

Replace entire content:

```html
{% extends "base.html" %}
{% block title %}RSS Sources{% endblock %}

{% block head_extra %}
<style>
.inline-edit-form { display:none; padding:0.4rem 0; }
.inline-edit-form.active { display:flex; gap:0.35rem; flex-wrap:wrap; align-items:center; }
.inline-edit-form input {
    padding:0.3rem 0.45rem; border:1px solid #d1d5db; border-radius:4px; font-size:0.8rem; background:var(--bg); color:var(--text);
}
.dark .inline-edit-form input { border-color: #334155; background: #0f172a; color: #e2e8f0; }
.test-results {
    display:none; margin-top:0.4rem; padding:0.6rem 0.75rem;
    background:#f9fafb; border:1px solid #e5e7eb; border-radius:0.375rem;
    font-size:0.8rem; max-height:250px; overflow-y:auto;
}
.dark .test-results { background: #0f172a; border-color: #334155; }
.test-results.active { display:block; }
.test-article { padding:0.35rem 0; border-bottom:1px solid #e5e7eb; }
.dark .test-article { border-bottom-color: #334155; }
.test-article:last-child { border-bottom:none; }
.test-article a { font-weight:500; color: #2563eb; }
.dark .test-article a { color: #60a5fa; }
.test-article .test-meta { font-size:0.72rem; color:#6b7280; }
.dark .test-article .test-meta { color: #94a3b8; }
.test-article .test-excerpt { font-size:0.78rem; color:#6b7280; margin-top:0.15rem; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }
.dark .test-article .test-excerpt { color: #94a3b8; }
</style>
{% endblock %}

{% block content %}

<h1 class="text-2xl font-bold text-gray-900 dark:text-white mb-1">📡 RSS Sources</h1>
<p class="text-sm text-gray-500 dark:text-slate-400 mb-6" id="source-count">
    {{ sources|length }} sources configured
</p>

{# ── Add Feed Form ── #}
<div class="rounded-xl shadow-sm border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 p-5 sm:p-6 mb-6">
    <h3 class="text-base font-semibold text-gray-900 dark:text-white mb-4">Add Feed</h3>
    <form id="add-feed-form" class="flex flex-wrap gap-3 items-end">
        <div class="flex-1 min-w-[180px]">
            <label class="block text-xs font-medium text-gray-500 dark:text-slate-400 mb-1">Feed URL *</label>
            <input type="url" name="feed_url" required placeholder="https://example.com/rss"
                   class="w-full rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-gray-900 dark:text-white text-sm py-2 px-3 focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
        </div>
        <div class="flex-1 min-w-[130px]">
            <label class="block text-xs font-medium text-gray-500 dark:text-slate-400 mb-1">Name *</label>
            <input type="text" name="name" required placeholder="My Feed"
                   class="w-full rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-gray-900 dark:text-white text-sm py-2 px-3 focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
        </div>
        <div class="flex-1 min-w-[100px]">
            <label class="block text-xs font-medium text-gray-500 dark:text-slate-400 mb-1">Category</label>
            <input type="text" name="category" placeholder="e.g. tech"
                   class="w-full rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-gray-900 dark:text-white text-sm py-2 px-3 focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
        </div>
        <div class="flex-1 min-w-[110px]">
            <label class="block text-xs font-medium text-gray-500 dark:text-slate-400 mb-1">Site URL</label>
            <input type="url" name="site_url" placeholder="https://..."
                   class="w-full rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-gray-900 dark:text-white text-sm py-2 px-3 focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
        </div>
        <button type="submit" class="rounded-lg bg-blue-600 text-white px-4 py-2 text-sm font-medium hover:bg-blue-700 transition-colors active:scale-95 whitespace-nowrap">Add Feed</button>
    </form>
    <div id="add-feedback" class="mt-3 text-sm hidden"></div>
</div>

{% if sources %}
<div class="rounded-xl shadow-sm border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden">
<table class="w-full text-sm">
    <thead>
        <tr class="bg-gray-50 dark:bg-slate-800 text-xs uppercase text-gray-500 dark:text-slate-400 tracking-wider">
            <th class="text-left px-4 py-3 font-medium">Name</th>
            <th class="text-left px-4 py-3 font-medium">Category</th>
            <th class="text-left px-4 py-3 font-medium">Status</th>
            <th class="text-left px-4 py-3 font-medium">Last Fetched</th>
            <th class="text-left px-4 py-3 font-medium w-[130px]">Actions</th>
        </tr>
    </thead>
    <tbody>
        {% for s in sources %}
        <tr id="source-row-{{ s.id }}" class="border-t border-gray-50 dark:border-slate-800 hover:bg-gray-50/50 dark:hover:bg-slate-800/50 transition-colors">
            <td class="px-4 py-3">
                <div id="source-display-{{ s.id }}">
                    <strong class="text-gray-900 dark:text-white">{{ s.name }}</strong>
                    {% if s.site_url %}
                    <br><small><a href="{{ s.site_url }}" target="_blank" rel="noopener" class="text-blue-600 dark:text-blue-400 hover:underline">{{ s.site_url[:60] }}</a></small>
                    {% endif %}
                </div>
                <div id="source-edit-{{ s.id }}" class="inline-edit-form">
                    <input type="text" id="edit-name-{{ s.id }}" value="{{ s.name|e }}" placeholder="Name" class="w-[120px] rounded border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-gray-900 dark:text-white text-xs py-1 px-2 focus:ring-2 focus:ring-blue-500">
                    <input type="url" id="edit-feed-{{ s.id }}" value="{{ s.feed_url|e }}" placeholder="Feed URL" class="w-[180px] rounded border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-gray-900 dark:text-white text-xs py-1 px-2 focus:ring-2 focus:ring-blue-500">
                    <input type="text" id="edit-cat-{{ s.id }}" value="{{ s.category or '' }}" placeholder="Category" class="w-[90px] rounded border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-gray-900 dark:text-white text-xs py-1 px-2 focus:ring-2 focus:ring-blue-500">
                    <input type="url" id="edit-site-{{ s.id }}" value="{{ s.site_url or '' }}" placeholder="Site URL" class="w-[150px] rounded border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-gray-900 dark:text-white text-xs py-1 px-2 focus:ring-2 focus:ring-blue-500">
                    <button onclick="saveEdit({{ s.id }})" class="rounded bg-blue-600 text-white text-xs px-2 py-1 cursor-pointer hover:bg-blue-700 transition-colors">Save</button>
                    <button onclick="cancelEdit({{ s.id }})" class="rounded border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-gray-700 dark:text-slate-300 text-xs px-2 py-1 cursor-pointer hover:bg-gray-50 dark:hover:bg-slate-700 transition-colors">Cancel</button>
                </div>
            </td>
            <td class="px-4 py-3">
                <span id="cat-badge-{{ s.id }}">
                    <span class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap
                        {% if s.category|lower == 'markets' %}bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-300
                        {% elif s.category|lower == 'politics' %}bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300
                        {% elif s.category|lower == 'world' %}bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300
                        {% elif s.category|lower == 'tech' %}bg-indigo-100 text-indigo-800 dark:bg-indigo-900 dark:text-indigo-300
                        {% else %}bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300{% endif %}
                    ">{{ s.category or '—' }}</span>
                </span>
            </td>
            <td class="px-4 py-3">
                <span id="status-badge-{{ s.id }}">
                {% if s.is_active %}
                <span class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300">Active</span>
                {% else %}
                <span class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300">Inactive</span>
                {% endif %}
                </span>
            </td>
            <td class="px-4 py-3 text-xs text-gray-500 dark:text-slate-400" id="last-fetched-{{ s.id }}">
                {% if s.last_fetched_at %}{{ s.last_fetched_at[:16] }}{% else %}<span>Never</span>{% endif %}
            </td>
            <td class="px-4 py-3">
                <div class="flex items-center gap-1">
                    <button id="test-btn-{{ s.id }}" onclick="testSource({{ s.id }})" title="Scrape & summarize this feed"
                            class="flex items-center justify-center w-7 h-7 rounded border border-gray-200 dark:border-slate-700 text-gray-400 dark:text-slate-500 hover:text-blue-600 hover:border-blue-300 dark:hover:text-blue-400 dark:hover:border-blue-600 transition-colors bg-white dark:bg-slate-900 cursor-pointer text-xs">🧪</button>
                    <button onclick="editSource({{ s.id }})" title="Edit"
                            class="flex items-center justify-center w-7 h-7 rounded border border-gray-200 dark:border-slate-700 text-gray-400 dark:text-slate-500 hover:text-blue-600 hover:border-blue-300 dark:hover:text-blue-400 dark:hover:border-blue-600 transition-colors bg-white dark:bg-slate-900 cursor-pointer text-xs">✏️</button>
                    <button onclick="toggleSource({{ s.id }}, {{ 'false' if s.is_active else 'true' }})" title="{{ 'Deactivate' if s.is_active else 'Activate' }}"
                            class="flex items-center justify-center w-7 h-7 rounded border border-gray-200 dark:border-slate-700 text-gray-400 dark:text-slate-500 hover:text-blue-600 hover:border-blue-300 dark:hover:text-blue-400 dark:hover:border-blue-600 transition-colors bg-white dark:bg-slate-900 cursor-pointer text-xs">{{ '⏸' if s.is_active else '▶' }}</button>
                    <button onclick="deleteSource({{ s.id }}, '{{ s.name|e }}')" title="Delete this feed and all its articles"
                            class="flex items-center justify-center w-7 h-7 rounded border border-gray-200 dark:border-slate-700 text-gray-400 dark:text-slate-500 hover:text-red-600 hover:border-red-300 dark:hover:text-red-400 dark:hover:border-red-600 transition-colors bg-white dark:bg-slate-900 cursor-pointer text-xs">🗑</button>
                </div>
            </td>
        </tr>
        <tr id="test-results-row-{{ s.id }}" class="hidden border-t border-gray-50 dark:border-slate-800">
            <td colspan="5" class="px-4 pb-4">
                <div id="test-results-{{ s.id }}" class="test-results"></div>
            </td>
        </tr>
        {% endfor %}
    </tbody>
</table>
</div>
{% else %}
<div class="flex flex-col items-center justify-center py-16 text-center">
    <div class="text-6xl mb-4">📡</div>
    <h3 class="text-lg font-semibold text-gray-900 dark:text-white mb-2">No sources configured</h3>
    <p class="text-gray-500 dark:text-slate-400">Add an RSS feed using the form above.</p>
</div>
{% endif %}

<script>
/* All JavaScript from the original sources.html stays identical — only CSS classes
   in the HTML above changed. The functions editSource, cancelEdit, saveEdit,
   testSource, resetTestBtn, escHtml, toggleSource, deleteSource, and the
   add-feed-form submit handler remain exactly as in the original file. */
// ── Add Feed ──
document.getElementById('add-feed-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = e.target;
    const btn = form.querySelector('button[type="submit"]');
    const fb = document.getElementById('add-feedback');
    btn.disabled = true; btn.textContent = 'Adding...'; fb.style.display = 'none';

    try {
        const body = {
            feed_url: form.feed_url.value.trim(),
            name: form.name.value.trim(),
            category: form.category.value.trim(),
            site_url: form.site_url.value.trim(),
        };
        const res = await fetch('/api/sources', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(body)
        });
        if (res.status === 401) {
            fb.style.display = 'block'; fb.style.color = '#c00';
            fb.innerHTML = '🔒 <a href="/login">Log in</a> first to add feeds.';
            btn.disabled = false; btn.textContent = 'Add Feed';
            return;
        }
        const data = await res.json();
        fb.style.display = 'block';
        if (res.ok) {
            fb.style.color = '#155724';
            fb.textContent = '✅ Feed added! Reloading...';
            setTimeout(() => location.reload(), 800);
        } else {
            fb.style.color = '#721c24';
            fb.textContent = '❌ ' + (data.detail || 'Failed');
        }
    } catch (err) {
        fb.style.display = 'block'; fb.style.color = '#721c24'; fb.textContent = '❌ Network error';
    }
    btn.disabled = false; btn.textContent = 'Add Feed';
});

function editSource(id) {
    document.getElementById('source-display-' + id).style.display = 'none';
    document.getElementById('source-edit-' + id).classList.add('active');
}
function cancelEdit(id) {
    document.getElementById('source-display-' + id).style.display = '';
    document.getElementById('source-edit-' + id).classList.remove('active');
}
async function saveEdit(id) {
    const name = document.getElementById('edit-name-' + id).value.trim();
    const feed_url = document.getElementById('edit-feed-' + id).value.trim();
    const category = document.getElementById('edit-cat-' + id).value.trim();
    const site_url = document.getElementById('edit-site-' + id).value.trim();
    try {
        const res = await fetch('/api/sources/' + id, {
            method: 'PUT', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name, feed_url, category, site_url})
        });
        if (res.status === 401) { alert('🔒 Please log in via /admin first to edit feeds.'); cancelEdit(id); return; }
        if (res.ok) { location.reload(); }
        else { const data = await res.json(); alert('❌ ' + (data.detail || 'Edit failed')); }
    } catch (err) { alert('❌ Network error'); }
}
async function testSource(id) {
    const btn = document.getElementById('test-btn-' + id);
    const resultsRow = document.getElementById('test-results-row-' + id);
    const resultsDiv = document.getElementById('test-results-' + id);
    btn.textContent = '⏳'; btn.disabled = true;
    resultsRow.classList.remove('hidden');
    resultsDiv.classList.add('active');
    resultsDiv.innerHTML = '<span style="color:#6b7280;">⏳ Scraping & summarizing...</span>';
    try {
        const res = await fetch('/api/sources/' + id + '/test', {method: 'POST'});
        if (res.status === 401) {
            resultsDiv.innerHTML = '<span style="color:#c00;">🔒 Login required. <a href="/login">Log in</a> first.</span>';
            resetTestBtn(id, btn, resultsRow); return;
        }
        const data = await res.json();
        if (!data.ok) {
            resultsDiv.innerHTML = '<span style="color:#721c24;">❌ Failed to start test</span>';
            resetTestBtn(id, btn, resultsRow); return;
        }
    } catch (err) {
        resultsDiv.innerHTML = '<span style="color:#721c24;">❌ Network error</span>';
        resetTestBtn(id, btn, resultsRow); return;
    }
    let attempts = 0; const maxAttempts = 60;
    async function poll() {
        try {
            const srcRes = await fetch('/api/sources/' + id);
            const src = await srcRes.json();
            const lastFetched = src.last_fetched_at;
            if (lastFetched && attempts > 1) {
                const artRes = await fetch('/api/sources/' + id + '/articles?limit=5');
                const artData = await artRes.json();
                const articles = artData.articles || [];
                const summarized = articles.filter(a => a.status === 'summarized').length;
                const lfCell = document.getElementById('last-fetched-' + id);
                if (lfCell) lfCell.textContent = lastFetched ? lastFetched.substring(0, 16) : '—';
                btn.textContent = '✅ ' + articles.length; btn.style.color = '#155724';
                if (articles.length === 0) {
                    resultsDiv.innerHTML = '<span style="color:#6b7280;">No new articles found in this feed.</span>';
                } else {
                    let html = '<div style="margin-bottom:0.25rem;font-weight:500;color:#2563eb;">📰 ' + articles.length + ' article(s) fetched, ' + summarized + ' summarized</div>';
                    for (const a of articles) {
                        const statusIcon = a.status === 'summarized' ? '✅' : a.status === 'failed' ? '❌' : a.status === 'raw' ? '📄' : '⏳';
                        html += '<div class="test-article"><a href="/article/' + a.id + '">' + escHtml(a.title || 'Untitled') + '</a><div class="test-meta">' + statusIcon + ' ' + a.status;
                        if (a.url) html += ' · <a href="' + a.url + '" target="_blank" rel="noopener" style="font-size:0.72rem;">View original →</a>';
                        html += '</div>';
                        if (a.summary_text) html += '<div class="test-excerpt">' + escHtml(a.summary_text.substring(0, 200)) + '…</div>';
                        html += '</div>';
                    }
                    resultsDiv.innerHTML = html;
                }
                setTimeout(() => { resultsRow.classList.add('hidden'); resultsDiv.classList.remove('active'); }, 15000);
                resetTestBtn(id, btn, resultsRow, false); return;
            }
            attempts++;
            if (attempts < maxAttempts) { setTimeout(poll, 2000); }
            else { resultsDiv.innerHTML = '<span style="color:#6b7280;">⏱ Timed out waiting for results. Check Admin panel.</span>'; resetTestBtn(id, btn, resultsRow); }
        } catch (err) { resultsDiv.innerHTML = '<span style="color:#721c24;">❌ Error polling status</span>'; resetTestBtn(id, btn, resultsRow); }
    }
    poll();
}
function resetTestBtn(id, btn, resultsRow, hideResults = true) {
    setTimeout(() => { btn.textContent = '🧪'; btn.disabled = false; btn.style.color = ''; }, hideResults ? 500 : 3000);
}
function escHtml(str) { const div = document.createElement('div'); div.textContent = str; return div.innerHTML; }
async function toggleSource(id, makeActive) {
    try {
        const res = await fetch('/api/sources/' + id, { method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({is_active: makeActive}) });
        if (res.status === 401) { alert('🔒 Please log in via /admin first.'); return; }
        if (res.ok) location.reload();
        else { const data = await res.json(); alert('❌ ' + (data.detail || 'Toggle failed')); }
    } catch (err) { alert('❌ Network error'); }
}
async function deleteSource(id, name) {
    if (!confirm('Delete "' + name + '" and all its articles?\n\nExisting digests keep their text, but linked articles will be removed.')) return;
    const row = document.getElementById('source-row-' + id);
    const btns = row.querySelectorAll('button'); btns.forEach(b => b.disabled = true);
    try {
        const res = await fetch('/api/sources/' + id, {method: 'DELETE'});
        if (res.status === 401) { alert('🔒 Please log in via /admin first.'); btns.forEach(b => b.disabled = false); return; }
        if (res.ok) {
            row.remove();
            const resultsRow = document.getElementById('test-results-row-' + id);
            if (resultsRow) resultsRow.remove();
            const remaining = document.querySelectorAll('tbody tr[id^="source-row-"]').length;
            document.getElementById('source-count').textContent = remaining + ' sources configured';
            if (remaining === 0) location.reload();
        } else { const data = await res.json(); alert('❌ ' + (data.detail || 'Delete failed')); }
    } catch (err) { alert('❌ Network error'); }
    btns.forEach(b => b.disabled = false); }
</script>

{% endblock %}
```

Note: The actual implementation must copy the **exact, complete** JavaScript from the original `sources.html` — the JS block above is representative. When implementing, copy the full original `<script>` block unchanged (only the HTML classes above change).

- [ ] **Step 2: Test sources page**

Visit `/sources`. Verify:
- Add feed form renders with Tailwind inputs
- Table with rounded container, subtle hover rows
- Category badges
- Status badges
- Actions buttons (test, edit, toggle, delete)
- Empty state

- [ ] **Step 3: Commit**

```bash
git add app/web/templates/sources.html
git commit -m "feat: convert sources page to Tailwind"
```

---

### Task 8: Convert Settings & Admin Pages (settings.html + admin.html)

**Files:**
- Modify: `app/web/templates/settings.html`
- Modify: `app/web/templates/admin.html`

- [ ] **Step 1: Write the new admin.html**

Replace entire content. Key structure (full template in plan — same pattern as above):
- Remove `style="..."` attributes, replace with Tailwind classes
- Model selector card: `flex items-center gap-3 p-4 rounded-xl border`
- Admin grid: `grid grid-cols-1 md:grid-cols-2 gap-4`
- Cards: `rounded-xl shadow-sm border p-5 sm:p-6`
- Buttons: `rounded-lg bg-blue-600 text-white px-4 py-2 text-sm font-medium hover:bg-blue-700 transition-colors active:scale-95`
- Status dashboard table: same rounded container + table pattern as sources
- Running jobs card: same pattern
- All JavaScript kept identical to original

```html
{% extends "base.html" %}
{% block title %}Admin Panel{% endblock %}

{% block content %}

<h1 class="text-2xl font-bold text-gray-900 dark:text-white mb-1">⚙️ Admin Panel</h1>
<p class="text-sm text-gray-500 dark:text-slate-400 mb-6">Manual controls and system status</p>

{# ── Running Jobs ── #}
<div id="running-jobs" class="hidden rounded-xl shadow-sm border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 p-5 mb-6">
    <div class="flex items-center gap-2 mb-3">
        <span class="text-lg">🔄</span>
        <strong class="text-gray-900 dark:text-white">Running Jobs</strong>
    </div>
    <div id="jobs-list" class="text-sm"></div>
</div>

{# ── Model Selector ── #}
<div class="flex items-center gap-3 flex-wrap rounded-xl shadow-sm border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 p-4 mb-6">
    <label class="text-sm font-medium text-gray-700 dark:text-slate-300 whitespace-nowrap">🤖 LLM Model:</label>
    <select id="model-select" class="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-gray-700 dark:text-slate-300 text-sm py-2 px-3 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 min-w-[200px]">
        <option value="gemma-4-31b-it">Gemma 4 31B (Gemini)</option>
        <option value="gemini-2.5-flash">Gemini 2.5 Flash</option>
        <option value="llama-3.3-70b-versatile">Llama 3.3 70B (Groq)</option>
        <option value="deepseek-chat">DeepSeek Chat</option>
    </select>
    <small class="text-gray-400 dark:text-slate-500 text-xs">Select model for summarization &amp; digest regeneration</small>
</div>

{# ── Manual Controls ── #}
<div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-8">
    {# Scrape #}
    <div class="rounded-xl shadow-sm border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 p-5 sm:p-6">
        <h3 class="text-base font-semibold text-gray-900 dark:text-white mb-1">🔄 Scraping</h3>
        <p class="text-sm text-gray-500 dark:text-slate-400 mb-4">Fetch new articles from all configured RSS feeds.</p>
        <label class="block text-xs font-medium text-gray-500 dark:text-slate-400 mb-1">Start date (optional)</label>
        <input type="date" id="scrape-start" class="w-full rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-gray-900 dark:text-white text-sm py-2 px-3 mb-3 focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
        <label class="block text-xs font-medium text-gray-500 dark:text-slate-400 mb-1">End date (optional)</label>
        <input type="date" id="scrape-end" class="w-full rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-gray-900 dark:text-white text-sm py-2 px-3 mb-3 focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
        <small class="block text-xs text-gray-400 dark:text-slate-500 mb-4">Leave both empty to scrape the last 24 hours.</small>
        <button id="btn-scrape" onclick="triggerScrape()" class="rounded-lg bg-blue-600 text-white px-4 py-2 text-sm font-medium hover:bg-blue-700 transition-colors active:scale-95">Run Scrape Now</button>
        <pre id="scrape-result" class="hidden mt-3 p-3 rounded-lg bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-xs font-mono text-gray-700 dark:text-slate-300 overflow-x-auto"></pre>
    </div>

    {# Summarize #}
    <div class="rounded-xl shadow-sm border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 p-5 sm:p-6">
        <h3 class="text-base font-semibold text-gray-900 dark:text-white mb-1">🤖 Summarization</h3>
        <p class="text-sm text-gray-500 dark:text-slate-400 mb-4">Summarize all raw articles and generate daily digests.</p>
        <button id="btn-summarize" onclick="triggerSummarize()" class="rounded-lg bg-blue-600 text-white px-4 py-2 text-sm font-medium hover:bg-blue-700 transition-colors active:scale-95">Run Summarization Now</button>
        <pre id="summarize-result" class="hidden mt-3 p-3 rounded-lg bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-xs font-mono text-gray-700 dark:text-slate-300 overflow-x-auto"></pre>
    </div>
</div>

{# ── Status Dashboard ── #}
<div class="rounded-xl shadow-sm border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 p-5 sm:p-6">
    <h3 class="text-base font-semibold text-gray-900 dark:text-white mb-4">📊 Status Overview</h3>
    <div id="status-dashboard"><p class="text-gray-400 dark:text-slate-500 text-sm">Loading...</p></div>
</div>

{# ── JavaScript: Copy the ENTIRE <script>...</script> block from the ORIGINAL admin.html on disk — all functions (triggerScrape, triggerSummarize, loadStatus, regenDigest, getProviderForModel, escHtml), model-select init, and loadStatus() call are preserved verbatim with zero changes. Use this command if needed:
     git show HEAD:app/web/templates/admin.html | sed -n '/<script>/,/<\/script>/p'
   Paste the full output between <script> and </script> below. ── #}
<script>
/* Paste the full <script>...</script> content from original admin.html here */
</script>

{% endblock %}
```

When implementing, copy the **exact complete** `<script>` block from the original `admin.html`.

- [ ] **Step 2: Write the new settings.html**

The settings page is ~400 lines. Key pattern: remove all inline `style="..."` attributes, replace with Tailwind classes. Same structure as admin but with more sections (YouTube channels, RSS sources, unified run, status dashboard).

```html
{% extends "base.html" %}
{% block title %}Settings — Media Hub{% endblock %}

{% block head_extra %}
<style>
.inline-edit-form { display:none; padding:0.4rem 0; }
.inline-edit-form.active { display:flex; gap:0.35rem; flex-wrap:wrap; align-items:center; }
.inline-edit-form input {
    padding:0.3rem 0.45rem; border:1px solid #d1d5db; border-radius:4px; font-size:0.8rem; background:var(--bg); color:var(--text);
}
.dark .inline-edit-form input { border-color: #334155; background: #0f172a; color: #e2e8f0; }
.test-results {
    display:none; margin-top:0.4rem; padding:0.6rem 0.75rem;
    background:#f9fafb; border:1px solid #e5e7eb; border-radius:0.375rem;
    font-size:0.8rem; max-height:250px; overflow-y:auto;
}
.dark .test-results { background: #0f172a; border-color: #334155; }
.test-results.active { display:block; }
.test-article { padding:0.35rem 0; border-bottom:1px solid #e5e7eb; }
.dark .test-article { border-bottom-color: #334155; }
.test-article:last-child { border-bottom:none; }
.test-article a { font-weight:500; color: #2563eb; }
.dark .test-article a { color: #60a5fa; }
.test-article .test-meta { font-size:0.72rem; color:#6b7280; }
.dark .test-article .test-meta { color: #94a3b8; }
section:has(#btn-scrape) { display:none; }
.run-source-choice { display:inline-flex;align-items:center;gap:0.4rem;cursor:pointer;font-weight:600; }
.run-source { width:1.15rem;height:1.15rem;accent-color: #2563eb;cursor:pointer; }
</style>
{% endblock %}

{% block content %}

<h1 class="text-2xl font-bold text-gray-900 dark:text-white mb-6">⚙️ Settings</h1>

{# ── Model Selector ── #}
<div class="flex items-center gap-3 flex-wrap rounded-xl shadow-sm border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 p-4 mb-6">
    <label class="text-sm font-medium text-gray-700 dark:text-slate-300 whitespace-nowrap">🤖 LLM Model:</label>
    <select id="model-select" class="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-gray-700 dark:text-slate-300 text-sm py-2 px-3 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 min-w-[200px]">
        <option value="gemma-4-31b-it">Gemma 4 31B (Gemini)</option>
        <option value="gemini-2.5-flash">Gemini 2.5 Flash</option>
        <option value="llama-3.3-70b-versatile">Llama 3.3 70B (Groq)</option>
        <option value="deepseek-chat">DeepSeek Chat</option>
    </select>
    <small class="text-gray-400 dark:text-slate-500 text-xs">Model used for summarization &amp; digest regeneration</small>
</div>

{# ── Running Jobs ── #}
<div id="running-jobs" class="hidden rounded-xl shadow-sm border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 p-5 mb-6">
    <div class="flex items-center gap-2 mb-3">
        <span class="text-lg">🔄</span>
        <strong class="text-gray-900 dark:text-white">Running Jobs</strong>
    </div>
    <div id="jobs-list" class="text-sm"></div>
</div>

{# ── Unified Sources & Run ── #}
<section class="mb-8">
    <h2 class="text-lg font-semibold text-gray-900 dark:text-white mb-1">Unified Sources &amp; Run</h2>
    <p class="text-sm text-gray-500 dark:text-slate-400 mb-4">Selection applies only to this run. Permanent active state is unchanged.</p>
    <div class="rounded-xl shadow-sm border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 p-5 sm:p-6">
        <div class="flex gap-2 flex-wrap mb-4">
            <button type="button" class="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-gray-600 dark:text-slate-400 text-sm px-3 py-1.5 hover:text-blue-600 hover:border-blue-300 dark:hover:text-blue-400 dark:hover:border-blue-600 transition-colors" onclick="setRunSelection(true)">Select active</button>
            <button type="button" class="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-gray-600 dark:text-slate-400 text-sm px-3 py-1.5 hover:text-blue-600 hover:border-blue-300 dark:hover:text-blue-400 dark:hover:border-blue-600 transition-colors" onclick="setRunSelection(false)">Clear</button>
            <select id="source-type-filter" onchange="filterRunSources()" class="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-gray-700 dark:text-slate-300 text-sm py-1.5 px-3 focus:ring-2 focus:ring-blue-500">
                <option value="">All types</option><option value="rss">RSS</option><option value="youtube">YouTube</option>
            </select>
        </div>
        <div class="overflow-x-auto">
        <table class="w-full text-sm"><thead><tr class="bg-gray-50 dark:bg-slate-800 text-xs uppercase text-gray-500 dark:text-slate-400 tracking-wider"><th class="text-left px-4 py-3 font-medium">Run</th><th class="text-left px-4 py-3 font-medium">Type</th><th class="text-left px-4 py-3 font-medium">Source</th><th class="text-left px-4 py-3 font-medium">Permanent state</th><th class="text-left px-4 py-3 font-medium">Last checked</th></tr></thead>
        <tbody>
        {% for src in all_sources %}
        <tr class="run-source-row border-t border-gray-50 dark:border-slate-800 hover:bg-gray-50/50 dark:hover:bg-slate-800/50" data-type="{{ src.source_type }}">
            <td class="px-4 py-3"><label class="run-source-choice"><input class="run-source" type="checkbox" value="{{ src.id }}" data-active="{{ 1 if src.is_active else 0 }}" {% if src.is_active %}checked{% endif %} class="mr-2"> Select</label></td>
            <td class="px-4 py-3 text-xs font-medium text-gray-500 dark:text-slate-400">{{ src.source_type|upper }}</td>
            <td class="px-4 py-3 font-medium text-gray-900 dark:text-white">{{ src.name }}</td>
            <td class="px-4 py-3"><button class="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-gray-600 dark:text-slate-400 text-xs px-2.5 py-1 hover:text-blue-600 hover:border-blue-300 transition-colors" onclick="togglePermanent({{ src.id }}, {{ 'true' if src.is_active else 'false' }})">{{ 'Active' if src.is_active else 'Inactive' }}</button></td>
            <td class="px-4 py-3 text-xs text-gray-400 dark:text-slate-500">{{ src.last_fetched_at or 'Never' }}</td>
        </tr>
        {% endfor %}
        </tbody></table>
        </div>
        <div class="flex gap-3 flex-wrap mt-4 items-end">
            <label class="text-xs text-gray-500 dark:text-slate-400">Start date (optional)<br><input type="date" id="run-start" class="mt-1 rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-gray-900 dark:text-white text-sm py-2 px-3 focus:ring-2 focus:ring-blue-500"></label>
            <label class="text-xs text-gray-500 dark:text-slate-400">End date (optional)<br><input type="date" id="run-end" class="mt-1 rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-gray-900 dark:text-white text-sm py-2 px-3 focus:ring-2 focus:ring-blue-500"></label>
            <button id="btn-unified-run" class="rounded-lg bg-blue-600 text-white px-4 py-2 text-sm font-medium hover:bg-blue-700 transition-colors active:scale-95" onclick="startUnifiedRun()">Run selected sources</button>
        </div>
        <div id="unified-run-result" class="mt-4 text-sm"></div>
    </div>
</section>

{# ── Manual Triggers ── #}
<section class="mb-8">
    <h2 class="text-lg font-semibold text-gray-900 dark:text-white mb-4">🔄 Manual Sync</h2>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        {# Scrape #}
        <div class="rounded-xl shadow-sm border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 p-5 sm:p-6">
            <h3 class="text-base font-semibold text-gray-900 dark:text-white mb-1">📥 Scrape RSS Feeds</h3>
            <p class="text-sm text-gray-500 dark:text-slate-400 mb-4">Fetch new articles from all configured RSS feeds.</p>
            <label class="block text-xs font-medium text-gray-500 dark:text-slate-400 mb-1">Start date (optional)</label>
            <input type="date" id="scrape-start" class="w-full rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-gray-900 dark:text-white text-sm py-2 px-3 mb-3 focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
            <label class="block text-xs font-medium text-gray-500 dark:text-slate-400 mb-1">End date (optional)</label>
            <input type="date" id="scrape-end" class="w-full rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-gray-900 dark:text-white text-sm py-2 px-3 mb-3 focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
            <small class="block text-xs text-gray-400 dark:text-slate-500 mb-4">Leave both empty to scrape the last 24 hours.</small>
            <button id="btn-scrape" onclick="triggerScrape()" class="rounded-lg bg-blue-600 text-white px-4 py-2 text-sm font-medium hover:bg-blue-700 transition-colors active:scale-95">Run RSS Scrape</button>
            <pre id="scrape-result" class="hidden mt-3 p-3 rounded-lg bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-xs font-mono text-gray-700 dark:text-slate-300 overflow-x-auto"></pre>
        </div>

        {# Summarize #}
        <div class="rounded-xl shadow-sm border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 p-5 sm:p-6">
            <h3 class="text-base font-semibold text-gray-900 dark:text-white mb-1">🤖 Summarize &amp; Digest</h3>
            <p class="text-sm text-gray-500 dark:text-slate-400 mb-4">Summarize all raw articles and generate daily digests (RSS + YouTube).</p>
            <button id="btn-summarize" onclick="triggerSummarize()" class="rounded-lg bg-blue-600 text-white px-4 py-2 text-sm font-medium hover:bg-blue-700 transition-colors active:scale-95">Run Summarization</button>
            <pre id="summarize-result" class="hidden mt-3 p-3 rounded-lg bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-xs font-mono text-gray-700 dark:text-slate-300 overflow-x-auto"></pre>
        </div>

        {# YouTube Scrape #}
        <div class="rounded-xl shadow-sm border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 p-5 sm:p-6">
            <h3 class="text-base font-semibold text-gray-900 dark:text-white mb-1">🎬 Scrape YouTube</h3>
            <p class="text-sm text-gray-500 dark:text-slate-400 mb-4">Fetch transcripts from configured YouTube channels.</p>
            <button id="btn-youtube" onclick="triggerJob('youtube')" class="rounded-lg bg-blue-600 text-white px-4 py-2 text-sm font-medium hover:bg-blue-700 transition-colors active:scale-95">Run YouTube Scrape</button>
            <span id="status-youtube" class="inline-block mt-2 text-sm italic text-gray-400 dark:text-slate-500"></span>
        </div>
    </div>
</section>

{# ── Status Overview ── #}
<section class="mb-8">
    <h2 class="text-lg font-semibold text-gray-900 dark:text-white mb-4">📊 Status Overview</h2>
    <div class="rounded-xl shadow-sm border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 p-5 sm:p-6">
        <div id="status-dashboard"><p class="text-gray-400 dark:text-slate-500 text-sm">Loading...</p></div>
    </div>
</section>

{# ── YouTube Channels ── #}
<section class="mb-8">
    <h2 class="text-lg font-semibold text-gray-900 dark:text-white mb-1">🎬 YouTube Channels</h2>
    <p class="text-sm text-gray-500 dark:text-slate-400 mb-4">Add channels by @handle (e.g. <code class="px-1.5 py-0.5 rounded bg-gray-100 dark:bg-slate-800 text-xs">@veritasium</code>) or full channel URL.</p>
    <form id="add-youtube-form" class="flex gap-2 mb-5" onsubmit="addYouTubeChannel(event)">
        <input type="text" id="youtube-handle" placeholder="@Handle or channel URL" required
            class="flex-1 rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-gray-900 dark:text-white py-2 px-4 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
        <button type="submit" class="rounded-lg bg-blue-600 text-white px-4 py-2 text-sm font-medium hover:bg-blue-700 transition-colors active:scale-95 whitespace-nowrap">Add Channel</button>
    </form>
    <div id="youtube-add-error" class="hidden text-red-600 dark:text-red-400 text-sm mb-4"></div>

    {% if youtube_sources %}
    <div class="overflow-x-auto rounded-xl shadow-sm border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900">
    <table class="w-full text-sm"><thead><tr class="bg-gray-50 dark:bg-slate-800 text-xs uppercase text-gray-500 dark:text-slate-400 tracking-wider"><th class="text-left px-4 py-3 font-medium">Channel</th><th class="text-left px-4 py-3 font-medium">Status</th><th class="text-left px-4 py-3 font-medium">Actions</th></tr></thead>
    <tbody>
        {% for src in youtube_sources %}
        <tr class="border-t border-gray-50 dark:border-slate-800 hover:bg-gray-50/50 dark:hover:bg-slate-800/50">
            <td class="px-4 py-3 font-medium text-gray-900 dark:text-white">{{ src.name }}</td>
            <td class="px-4 py-3"><span class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium {% if src.is_active %}bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300{% else %}bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-300{% endif %}">{{ 'Active' if src.is_active else 'Paused' }}</span></td>
            <td class="px-4 py-3">
                <div class="flex gap-2 items-center">
                    <button class="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-gray-600 dark:text-slate-400 text-xs px-2.5 py-1 hover:text-blue-600 hover:border-blue-300 dark:hover:text-blue-400 transition-colors" onclick="toggleYouTubeChannel({{ src.id }})">{{ '⏸ Pause' if src.is_active else '▶ Resume' }}</button>
                    <button class="rounded-lg border border-red-300 dark:border-red-800 bg-white dark:bg-slate-900 text-red-600 dark:text-red-400 text-xs px-2.5 py-1 hover:bg-red-50 dark:hover:bg-red-950 transition-colors" onclick="deleteYouTubeChannel({{ src.id }}, '{{ src.name | e }}')">🗑</button>
                </div>
            </td>
        </tr>
        {% endfor %}
    </tbody></table>
    </div>
    {% else %}
    <p class="text-sm text-gray-400 dark:text-slate-500">No YouTube channels added yet.</p>
    {% endif %}
</section>

{# ── RSS Sources ── #}
<section class="mb-8">
    <h2 class="text-lg font-semibold text-gray-900 dark:text-white mb-1">📡 RSS Sources</h2>
    <p class="text-sm text-gray-500 dark:text-slate-400">
        {{ rss_sources|length }} source{{ 's' if rss_sources|length != 1 else '' }} configured.
        <a href="/sources" class="text-blue-600 dark:text-blue-400 hover:underline ml-1">Manage all RSS sources →</a>
    </p>
</section>

{# ── JavaScript: Copy the ENTIRE <script>...</script> block from the ORIGINAL settings.html on disk — all functions (setRunSelection, filterRunSources, togglePermanent, startUnifiedRun, retryUnifiedRun, triggerScrape, triggerSummarize, triggerJob, pollStatus, addYouTubeChannel, toggleYouTubeChannel, deleteYouTubeChannel, loadStatus, regenDigest, getProviderForModel, escHtml), model-select init, and loadStatus() call are preserved verbatim with zero changes. Use this command if needed:
     git show HEAD:app/web/templates/settings.html | sed -n '/<script>/,/<\/script>/p'
   Paste the full output between <script> and </script> below. ── #}
<script>
/* Paste the full <script>...</script> content from original settings.html here */
</script>

{% endblock %}
```

When implementing, copy the **exact complete** `<script>` blocks from the original files.

- [ ] **Step 3: Test settings and admin pages**

Visit `/settings` and `/admin`. Verify all sections render correctly, forms work, buttons trigger actions.

- [ ] **Step 4: Commit**

```bash
git add app/web/templates/settings.html app/web/templates/admin.html
git commit -m "feat: convert settings and admin pages to Tailwind"
```

---

### Task 9: Convert Login Page (login.html)

**Files:**
- Modify: `app/web/templates/login.html`

- [ ] **Step 1: Write the new login.html**

Note: login.html does NOT extend base.html. It's standalone. Add the output.css link.

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Login — Media Hub</title>
    <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>📰</text></svg>" type="image/svg+xml">
    <script>
    (function() {
        const saved = localStorage.getItem('theme');
        const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        if (saved === 'dark' || (!saved && prefersDark)) {
            document.documentElement.setAttribute('data-theme', 'dark');
        }
        document.documentElement.classList.add('theme-ready');
    })();
    </script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="/static/output.css">
</head>
<body class="font-sans antialiased bg-gray-50 dark:bg-slate-900 text-gray-900 dark:text-white transition-colors min-h-screen flex items-center justify-center p-4">
    <main class="w-full max-w-sm">
        <div class="rounded-xl shadow-sm border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 p-8">
            <div class="text-center mb-6">
                <span class="text-4xl">📰</span>
                <h1 class="text-xl font-bold text-gray-900 dark:text-white mt-3">Media Hub</h1>
                <p class="text-sm text-gray-500 dark:text-slate-400 mt-1">Sign in to manage</p>
            </div>

            {% if error %}
            <div class="rounded-r-lg border-l-4 border-red-500 bg-red-50 dark:bg-red-950/20 p-3 mb-5 text-sm text-red-700 dark:text-red-300">{{ error }}</div>
            {% endif %}

            <form method="post" action="/login">
                <fieldset class="border-none p-0 m-0">
                    <label class="block mb-4">
                        <span class="text-sm font-medium text-gray-700 dark:text-slate-300">Username</span>
                        <input type="text" name="username" placeholder="Username" required autofocus
                               class="mt-1 w-full rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-gray-900 dark:text-white py-2.5 px-3.5 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
                    </label>
                    <label class="block mb-5">
                        <span class="text-sm font-medium text-gray-700 dark:text-slate-300">Password</span>
                        <input type="password" name="password" placeholder="Password" required
                               class="mt-1 w-full rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-gray-900 dark:text-white py-2.5 px-3.5 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
                    </label>
                </fieldset>
                <button type="submit" class="w-full rounded-lg bg-blue-600 text-white py-2.5 text-sm font-semibold hover:bg-blue-700 transition-colors active:scale-95">
                    Sign In
                </button>
            </form>
        </div>
    </main>
</body>
</html>
```

- [ ] **Step 2: Test login page**

Visit `/login`. Verify centered card, form inputs with focus rings, error state, dark mode works.

- [ ] **Step 3: Commit**

```bash
git add app/web/templates/login.html
git commit -m "feat: convert login page to Tailwind"
```

---

### Task 10: Final Cleanup

**Files:**
- Modify: `app/web/templates/base.html` (remove old style.css link)
- Delete/Archive: `app/web/static/style.css` (or keep for reference, remove link only)

- [ ] **Step 1: Remove old CSS link from base.html**

In `base.html`, remove the line:
```html
<link rel="stylesheet" href="/static/style.css">
```

- [ ] **Step 2: Full manual walkthrough**

Visit every page in both light and dark mode:
- `/` — daily digest
- `/digest/YYYY-MM-DD` — specific date
- `/article/<id>` — article page
- `/history` — digest history
- `/youtube` — YouTube digest
- `/youtube/history` — YouTube history
- `/sources` — RSS sources
- `/settings` — settings
- `/admin` — admin panel
- `/login` — login

On mobile viewport (≤768px): verify hamburger menu, drawer, channel pills, responsive grid.

Verify:
- Sidebar collapse works (desktop)
- Theme toggle works (desktop + mobile)
- YouTube subnav toggles
- Video footnotes expand/collapse
- All forms submit correctly
- No visual regressions or broken layouts

- [ ] **Step 3: Commit final cleanup**

```bash
git add app/web/templates/base.html
git commit -m "chore: remove old style.css link, UI modernization complete"
```
