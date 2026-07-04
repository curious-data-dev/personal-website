# Sidebar UX Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix sidebar collapse flicker on VPS, make YouTube subnav usable in collapsed mode, and migrate Sources management into Settings.

**Architecture:** Three independent fixes in `base.html` (blocking script for flicker, JS for YouTube temporary-expand), one route change in `routes.py` (redirect `/sources` → `/settings`), and a new collapsible section in `settings.html` with unified RSS + YouTube table.

**Tech Stack:** Python/FastAPI, Jinja2 templates, vanilla JS, localStorage

## Global Constraints

- No database schema changes
- No new API endpoints — reuse existing `/api/sources`, `/api/youtube/sources`, etc.
- Keep existing YouTube Channels section in settings unchanged
- Keep existing Unified Sources & Run section unchanged
- `/sources` page template kept on disk but unlinked
- Collapsible state persisted via localStorage matching existing pattern (`settings-<id>-open`)

---

### Task 1: Sidebar collapse flicker fix

**Files:**
- Modify: `app/web/templates/base.html`

- [ ] **Step 1: Add blocking script after `<body>` tag**

Find the `<body>` tag and add a blocking `<script>` immediately after it, following the exact same pattern as the existing theme script at lines 11-18:

```html
<body class="font-sans antialiased bg-gray-50 dark:bg-slate-900 text-gray-900 dark:text-white transition-colors{% if toc or sources %} has-sidebar{% endif %}">

    {# ── Blocking sidebar-collapse script — reads localStorage before paint ── #}
    <script>
    (function() {
        if (localStorage.getItem('sidebar-collapsed') === 'true') {
            document.body.classList.add('sidebar-collapsed');
        }
    })();
    </script>
```

The existing JS at lines 328-335 (`sidebarToggle` code) stays as-is as a backstop — no harm in double-applying the class.

- [ ] **Step 2: Verify no eslint/template errors**

```bash
python -c "from app.web.routes import templates; t = templates.get_template('base.html'); print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/web/templates/base.html
git commit -m "fix: prevent sidebar collapse flicker with blocking script before paint"
```

---

### Task 2: YouTube subnav usable when sidebar is collapsed

**Files:**
- Modify: `app/web/templates/base.html`

**Interfaces:**
- Consumes: `#sidebar`, `#youtubeNav`, `#youtubeSubnav`, `#youtubeChevron` (existing DOM)
- Produces: Temporary-expand behavior on collapsed sidebar YouTube click, click-outside collapse

- [ ] **Step 1: Remove CSS rule that hides subnav in collapsed mode**

Find and remove this rule (currently around line 152):

```css
.sidebar-collapsed #sidebar #youtubeSubnav { display: none !important; }
```

- [ ] **Step 2: Add JS for temporary expand on YouTube click**

Add this JS near the existing YouTube subnav code (around line 404) that handles the temporary-expand behavior:

```javascript
// ── YouTube temporary expand when sidebar is collapsed ──
(function() {
    const sidebar = document.getElementById('sidebar');
    const ytNav = document.getElementById('youtubeNav');
    if (!sidebar || !ytNav) return;

    let tempExpanded = false;

    ytNav.addEventListener('click', function(e) {
        if (!document.body.classList.contains('sidebar-collapsed')) return;
        // Only expand if we're on a YouTube page (ytNav is a toggle, not a link)
        // On non-YouTube pages, ytNav doesn't exist — the <a> link is present instead
        e.preventDefault();
        e.stopPropagation();
        document.body.classList.remove('sidebar-collapsed');
        tempExpanded = true;
    });

    document.addEventListener('click', function(e) {
        if (!tempExpanded) return;
        // If click is outside the sidebar, collapse it
        if (!sidebar.contains(e.target)) {
            document.body.classList.add('sidebar-collapsed');
            tempExpanded = false;
        }
    });

    // Clicking any nav link inside sidebar also collapses
    sidebar.querySelectorAll('a.sidebar-link').forEach(function(link) {
        link.addEventListener('click', function() {
            if (tempExpanded) {
                document.body.classList.add('sidebar-collapsed');
                tempExpanded = false;
            }
        });
    });

    // Sidebar toggle button: if tempExpanded, clear flag (toggle handles the rest)
    const toggleBtn = document.getElementById('sidebarToggle');
    if (toggleBtn) {
        toggleBtn.addEventListener('click', function() {
            tempExpanded = false;
        });
    }
})();
```

This must be placed after the DOM elements are guaranteed to exist — inside the same `<script>` block that contains the other sidebar JS, after `#youtubeNav` is known to exist. Place it right before or after the existing YouTube subnav code block.

- [ ] **Step 3: Verify template compiles**

```bash
python -c "from app.web.routes import templates; t = templates.get_template('base.html'); print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add app/web/templates/base.html
git commit -m "fix: youtube subnav temporarily expands sidebar in collapsed mode"
```

---

### Task 3: Remove Sources nav link and redirect

**Files:**
- Modify: `app/web/templates/base.html`
- Modify: `app/web/routes.py`

- [ ] **Step 1: Remove Sources link from sidebar nav**

In `base.html`, remove this block (currently around line 77-79):

```html
<a href="/sources" class="sidebar-link {% if request.url.path.startswith('/sources') %}sidebar-link-active{% endif %}">
    <span>📡</span><span class="sidebar-label">Sources</span>
</a>
```

- [ ] **Step 2: Change `/sources` route to redirect**

In `routes.py`, find the `sources_list` function (around line 415-429) and replace the entire function body with a redirect:

```python
@router.get("/sources", response_class=HTMLResponse)
async def sources_list(request: Request):
    """Redirect to settings page where sources are now managed."""
    return RedirectResponse(url="/settings", status_code=303)
```

Remove the unused `get_db`, `get_all_sources`, and `templates` imports if they're no longer needed — but check first that they're used elsewhere in routes.py (they almost certainly are).

- [ ] **Step 3: Verify route redirect works**

Start server and test:

```bash
curl -s -o /dev/null -w "%{http_code} %{redirect_url}" http://127.0.0.1:8000/sources
```

Expected: `303 http://127.0.0.1:8000/settings`

- [ ] **Step 4: Run full test suite**

```bash
python -m pytest tests/ -x -q
```

Expected: all tests pass (no tests directly test the sources page, but verify nothing breaks).

- [ ] **Step 5: Commit**

```bash
git add app/web/templates/base.html app/web/routes.py
git commit -m "fix: redirect /sources to /settings, remove nav link"
```

---

### Task 4: Unified Sources section in Settings

**Files:**
- Modify: `app/web/templates/settings.html`

**Interfaces:**
- Consumes: `all_sources` (list of dicts with `id`, `source_type`, `name`, `is_active`, `last_fetched_at`, and for RSS: `feed_url`, `category`, `site_url`)
- Produces: Collapsible "📡 Sources" section with combined RSS + YouTube table, add forms, inline edit, test, toggle, delete

- [ ] **Step 1: Add console.error polyfill for edge runtime bots**

*(Settings page has inline JS that may reference `console` — ensure no errors if console is undefined.)*

Not needed — all environments have `console`. Skip.

- [ ] **Step 1 (actual): Add "📡 Sources" collapsible section before "Unified Sources & Run"**

Insert the following HTML right before the `{# ── Unified Sources & Run ── #}` comment block (around line 62 in settings.html):

```html
{# ── Sources (RSS + YouTube) ── #}
<section class="mb-8">
    <h2 class="text-lg font-semibold text-gray-900 dark:text-white mb-1 cursor-pointer select-none flex items-center gap-2 hover:text-blue-600 dark:hover:text-blue-400 transition-colors" onclick="toggleCollapsible('settings-sources')">
        <span id="settings-sources-chevron" class="text-xs transition-transform">▶</span>
        📡 Sources
    </h2>
    <p class="text-sm text-gray-500 dark:text-slate-400 mb-4" id="settings-sources-count">
        {{ all_sources|length }} source{{ 's' if all_sources|length != 1 else '' }} configured
    </p>
    <div id="settings-sources" class="hidden rounded-xl shadow-sm border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 p-5 sm:p-6">

        {# ── Add buttons ── #}
        <div class="flex gap-2 mb-4">
            <button type="button" onclick="showSourceForm('rss')" class="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-gray-600 dark:text-slate-400 text-sm px-3 py-1.5 hover:text-blue-600 hover:border-blue-300 dark:hover:text-blue-400 dark:hover:border-blue-600 transition-colors">+ Add RSS Feed</button>
            <button type="button" onclick="showSourceForm('youtube')" class="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-gray-600 dark:text-slate-400 text-sm px-3 py-1.5 hover:text-blue-600 hover:border-blue-300 dark:hover:text-blue-400 dark:hover:border-blue-600 transition-colors">+ Add YouTube Channel</button>
        </div>

        {# ── Add RSS form ── #}
        <div id="add-rss-form" style="display:none;" class="mb-4 p-4 rounded-lg border border-gray-100 dark:border-slate-800 bg-gray-50 dark:bg-slate-800/50">
            <h4 class="text-sm font-semibold text-gray-900 dark:text-white mb-3">Add RSS Feed</h4>
            <form id="settings-add-rss" class="flex flex-wrap gap-3 items-end">
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
            <div id="settings-rss-feedback" class="mt-3 text-sm hidden"></div>
        </div>

        {# ── Add YouTube form ── #}
        <div id="add-youtube-form" style="display:none;" class="mb-4 p-4 rounded-lg border border-gray-100 dark:border-slate-800 bg-gray-50 dark:bg-slate-800/50">
            <h4 class="text-sm font-semibold text-gray-900 dark:text-white mb-3">Add YouTube Channel</h4>
            <form id="settings-add-youtube" class="flex gap-2 items-end" onsubmit="settingsAddYouTube(event)">
                <div class="flex-1 min-w-[200px]">
                    <label class="block text-xs font-medium text-gray-500 dark:text-slate-400 mb-1">Handle or Channel URL *</label>
                    <input type="text" id="settings-youtube-handle" required placeholder="@Handle or channel URL"
                           class="w-full rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-gray-900 dark:text-white text-sm py-2 px-3 focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
                </div>
                <button type="submit" class="rounded-lg bg-blue-600 text-white px-4 py-2 text-sm font-medium hover:bg-blue-700 transition-colors active:scale-95 whitespace-nowrap">Add Channel</button>
            </form>
            <div id="settings-youtube-feedback" class="mt-3 text-sm hidden"></div>
        </div>

        {# ── Unified sources table ── #}
        {% if all_sources %}
        <div class="overflow-x-auto">
        <table class="w-full text-sm">
            <thead>
                <tr class="bg-gray-50 dark:bg-slate-800 text-xs uppercase text-gray-500 dark:text-slate-400 tracking-wider">
                    <th class="text-left px-4 py-3 font-medium">Type</th>
                    <th class="text-left px-4 py-3 font-medium">Name</th>
                    <th class="text-left px-4 py-3 font-medium">Status</th>
                    <th class="text-left px-4 py-3 font-medium">Last Checked</th>
                    <th class="text-left px-4 py-3 font-medium w-[130px]">Actions</th>
                </tr>
            </thead>
            <tbody>
                {% for src in all_sources %}
                <tr id="settings-source-row-{{ src.id }}" class="border-t border-gray-50 dark:border-slate-800 hover:bg-gray-50/50 dark:hover:bg-slate-800/50">
                    <td class="px-4 py-3 text-xs font-medium text-gray-500 dark:text-slate-400 uppercase">{{ src.source_type }}</td>
                    <td class="px-4 py-3">
                        <div id="settings-src-display-{{ src.id }}">
                            <strong class="text-gray-900 dark:text-white">{{ src.name }}</strong>
                            {% if src.get('site_url') %}
                            <br><small><a href="{{ src.site_url }}" target="_blank" rel="noopener" class="text-blue-600 dark:text-blue-400 hover:underline">{{ src.site_url[:60] }}</a></small>
                            {% endif %}
                        </div>
                        <div id="settings-src-edit-{{ src.id }}" class="inline-edit-form">
                            <input type="text" id="settings-edit-name-{{ src.id }}" value="{{ src.name|e }}" placeholder="Name" class="w-[120px] rounded border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-gray-900 dark:text-white text-xs py-1 px-2 focus:ring-2 focus:ring-blue-500">
                            {% if src.source_type == 'rss' %}
                            <input type="url" id="settings-edit-feed-{{ src.id }}" value="{{ src.feed_url|e }}" placeholder="Feed URL" class="w-[180px] rounded border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-gray-900 dark:text-white text-xs py-1 px-2 focus:ring-2 focus:ring-blue-500">
                            <input type="text" id="settings-edit-cat-{{ src.id }}" value="{{ src.category or '' }}" placeholder="Category" class="w-[90px] rounded border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-gray-900 dark:text-white text-xs py-1 px-2 focus:ring-2 focus:ring-blue-500">
                            <input type="url" id="settings-edit-site-{{ src.id }}" value="{{ src.site_url or '' }}" placeholder="Site URL" class="w-[150px] rounded border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-gray-900 dark:text-white text-xs py-1 px-2 focus:ring-2 focus:ring-blue-500">
                            {% endif %}
                            <button onclick="settingsSaveEdit({{ src.id }}, '{{ src.source_type }}')" class="rounded bg-blue-600 text-white text-xs px-2 py-1 cursor-pointer hover:bg-blue-700 transition-colors">Save</button>
                            <button onclick="settingsCancelEdit({{ src.id }})" class="rounded border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-gray-700 dark:text-slate-300 text-xs px-2 py-1 cursor-pointer hover:bg-gray-50 dark:hover:bg-slate-700 transition-colors">Cancel</button>
                        </div>
                    </td>
                    <td class="px-4 py-3">
                        <span id="settings-status-badge-{{ src.id }}">
                        {% if src.is_active %}
                        <span class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300">Active</span>
                        {% else %}
                        <span class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300">Inactive</span>
                        {% endif %}
                        </span>
                    </td>
                    <td class="px-4 py-3 text-xs text-gray-500 dark:text-slate-400" id="settings-last-fetched-{{ src.id }}">
                        {% if src.last_fetched_at %}{{ src.last_fetched_at[:16] }}{% else %}<span>Never</span>{% endif %}
                    </td>
                    <td class="px-4 py-3">
                        <div class="flex items-center gap-1">
                            {% if src.source_type == 'rss' %}
                            <button id="settings-test-btn-{{ src.id }}" onclick="settingsTestSource({{ src.id }})" title="Scrape &amp; summarize this feed"
                                    class="flex items-center justify-center w-7 h-7 rounded border border-gray-200 dark:border-slate-700 text-gray-400 dark:text-slate-500 hover:text-blue-600 hover:border-blue-300 dark:hover:text-blue-400 dark:hover:border-blue-600 transition-colors bg-white dark:bg-slate-900 cursor-pointer text-xs">🧪</button>
                            {% endif %}
                            <button onclick="settingsEditSource({{ src.id }})" title="Edit"
                                    class="flex items-center justify-center w-7 h-7 rounded border border-gray-200 dark:border-slate-700 text-gray-400 dark:text-slate-500 hover:text-blue-600 hover:border-blue-300 dark:hover:text-blue-400 dark:hover:border-blue-600 transition-colors bg-white dark:bg-slate-900 cursor-pointer text-xs">✏️</button>
                            <button onclick="settingsToggleSource({{ src.id }}, '{{ src.source_type }}', {{ 'false' if src.is_active else 'true' }})" title="{{ 'Deactivate' if src.is_active else 'Activate' }}"
                                    class="flex items-center justify-center w-7 h-7 rounded border border-gray-200 dark:border-slate-700 text-gray-400 dark:text-slate-500 hover:text-blue-600 hover:border-blue-300 dark:hover:text-blue-400 dark:hover:border-blue-600 transition-colors bg-white dark:bg-slate-900 cursor-pointer text-xs">{{ '⏸' if src.is_active else '▶' }}</button>
                            <button onclick="settingsDeleteSource({{ src.id }}, '{{ src.source_type }}', '{{ src.name|e }}')" title="Delete"
                                    class="flex items-center justify-center w-7 h-7 rounded border border-gray-200 dark:border-slate-700 text-gray-400 dark:text-slate-500 hover:text-red-600 hover:border-red-300 dark:hover:text-red-400 dark:hover:border-red-600 transition-colors bg-white dark:bg-slate-900 cursor-pointer text-xs">🗑</button>
                        </div>
                    </td>
                </tr>
                <tr id="settings-test-row-{{ src.id }}" style="display:none;" class="border-t border-gray-50 dark:border-slate-800">
                    <td colspan="5" class="px-4 pb-4">
                        <div id="settings-test-results-{{ src.id }}" class="test-results"></div>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        </div>
        {% else %}
        <p class="text-sm text-gray-400 dark:text-slate-500 text-center py-8">No sources configured yet. Add an RSS feed or YouTube channel above.</p>
        {% endif %}
    </div>
</section>
```

- [ ] **Step 2: Add JS for Sources section**

Append this JS inside the existing `<script>` block at the bottom of `settings.html` (before `loadStatus();`):

```javascript
// ── Settings Sources: form visibility ──
function showSourceForm(type) {
    document.getElementById('add-rss-form').style.display = type === 'rss' ? 'block' : 'none';
    document.getElementById('add-youtube-form').style.display = type === 'youtube' ? 'block' : 'none';
}

// ── Settings Sources: Add RSS ──
document.getElementById('settings-add-rss').addEventListener('submit', async function(e) {
    e.preventDefault();
    const form = e.target;
    const btn = form.querySelector('button[type="submit"]');
    const fb = document.getElementById('settings-rss-feedback');
    btn.disabled = true; btn.textContent = 'Adding...'; fb.style.display = 'none';
    try {
        const body = {
            feed_url: form.feed_url.value.trim(),
            name: form.name.value.trim(),
            category: form.category.value.trim(),
            site_url: form.site_url.value.trim(),
        };
        const res = await fetch('/api/sources', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
        if (res.status === 401) {
            fb.style.display = 'block'; fb.style.color = '#c00';
            fb.innerHTML = '🔒 <a href="/login">Log in</a> first.';
            btn.disabled = false; btn.textContent = 'Add Feed';
            return;
        }
        const data = await res.json();
        fb.style.display = 'block';
        if (res.ok) { fb.style.color = '#155724'; fb.textContent = '✅ Feed added! Reloading...'; setTimeout(() => location.reload(), 800); }
        else { fb.style.color = '#721c24'; fb.textContent = '❌ ' + (data.detail || 'Failed'); }
    } catch(err) { fb.style.display = 'block'; fb.style.color = '#721c24'; fb.textContent = '❌ Network error'; }
    btn.disabled = false; btn.textContent = 'Add Feed';
});

// ── Settings Sources: Add YouTube ──
async function settingsAddYouTube(e) {
    e.preventDefault();
    const input = document.getElementById('settings-youtube-handle');
    const fb = document.getElementById('settings-youtube-feedback');
    const handle = input.value.trim();
    if (!handle) return;
    fb.style.display = 'none';
    try {
        const resp = await fetch('/api/youtube/sources', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({handle})});
        const data = await resp.json();
        if (resp.ok) { window.location.reload(); }
        else { fb.textContent = data.detail || 'Failed to add channel'; fb.style.color = '#721c24'; fb.style.display = 'block'; }
    } catch(err) { fb.textContent = 'Network error: ' + err.message; fb.style.color = '#721c24'; fb.style.display = 'block'; }
}

// ── Settings Sources: Edit ──
function settingsEditSource(id) {
    document.getElementById('settings-src-display-' + id).style.display = 'none';
    document.getElementById('settings-src-edit-' + id).classList.add('active');
}
function settingsCancelEdit(id) {
    document.getElementById('settings-src-display-' + id).style.display = '';
    document.getElementById('settings-src-edit-' + id).classList.remove('active');
}

async function settingsSaveEdit(id, sourceType) {
    const name = document.getElementById('settings-edit-name-' + id).value.trim();
    const body = { name };

    if (sourceType === 'rss') {
        body.feed_url = document.getElementById('settings-edit-feed-' + id).value.trim();
        body.category = document.getElementById('settings-edit-cat-' + id).value.trim();
        body.site_url = document.getElementById('settings-edit-site-' + id).value.trim();
    }

    const endpoint = sourceType === 'rss' ? '/api/sources/' + id : '/api/youtube/sources/' + id;
    const method = sourceType === 'rss' ? 'PUT' : 'PATCH';

    try {
        const res = await fetch(endpoint, {method, headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
        if (res.status === 401) { alert('🔒 Please log in first.'); settingsCancelEdit(id); return; }
        if (res.ok) { location.reload(); }
        else { const data = await res.json(); alert('❌ ' + (data.detail || 'Edit failed')); }
    } catch(err) { alert('❌ Network error'); }
}

// ── Settings Sources: Toggle ──
async function settingsToggleSource(id, sourceType, makeActive) {
    const endpoint = sourceType === 'rss'
        ? '/api/sources/' + id
        : '/api/youtube/sources/' + id + '/toggle';
    const method = sourceType === 'rss' ? 'PATCH' : 'POST';
    const body = sourceType === 'rss' ? JSON.stringify({is_active: makeActive}) : undefined;
    try {
        const res = await fetch(endpoint, {method, headers:{'Content-Type':'application/json'}, body});
        if (res.status === 401) { alert('🔒 Please log in first.'); return; }
        if (res.ok) location.reload();
        else { const data = await res.json(); alert('❌ ' + (data.detail || 'Toggle failed')); }
    } catch(err) { alert('❌ Network error'); }
}

// ── Settings Sources: Delete ──
async function settingsDeleteSource(id, sourceType, name) {
    if (!confirm('Delete "' + name + '" and all its content?')) return;
    const endpoint = sourceType === 'rss'
        ? '/api/sources/' + id
        : '/api/youtube/sources/' + id;
    try {
        const res = await fetch(endpoint, {method:'DELETE'});
        if (res.status === 401) { alert('🔒 Please log in first.'); return; }
        if (res.ok) {
            const row = document.getElementById('settings-source-row-' + id);
            if (row) row.remove();
            const testRow = document.getElementById('settings-test-row-' + id);
            if (testRow) testRow.remove();
            // Update count
            const remaining = document.querySelectorAll('tr[id^="settings-source-row-"]').length;
            const countEl = document.getElementById('settings-sources-count');
            if (countEl) countEl.textContent = remaining + ' source' + (remaining !== 1 ? 's' : '') + ' configured';
            if (remaining === 0) location.reload();
        } else {
            const data = await res.json(); alert('❌ ' + (data.detail || 'Delete failed'));
        }
    } catch(err) { alert('❌ Network error'); }
}

// ── Settings Sources: Test RSS ──
async function settingsTestSource(id) {
    const btn = document.getElementById('settings-test-btn-' + id);
    const resultsRow = document.getElementById('settings-test-row-' + id);
    const resultsDiv = document.getElementById('settings-test-results-' + id);

    btn.textContent = '⏳'; btn.disabled = true;
    resultsRow.style.display = '';
    resultsDiv.classList.add('active');
    resultsDiv.innerHTML = '<span style="color:var(--text-muted);">⏳ Scraping & summarizing...</span>';

    try {
        const res = await fetch('/api/sources/' + id + '/test', {method:'POST'});
        if (res.status === 401) {
            resultsDiv.innerHTML = '<span style="color:#c00;">🔒 Login required. <a href="/login">Log in</a> first.</span>';
            settingsResetTestBtn(id, btn, resultsRow);
            return;
        }
        const data = await res.json();
        if (!data.ok) {
            resultsDiv.innerHTML = '<span style="color:#721c24;">❌ Failed to start test</span>';
            settingsResetTestBtn(id, btn, resultsRow);
            return;
        }
    } catch(err) {
        resultsDiv.innerHTML = '<span style="color:#721c24;">❌ Network error</span>';
        settingsResetTestBtn(id, btn, resultsRow);
        return;
    }

    let attempts = 0;
    const maxAttempts = 60;
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
                const lfCell = document.getElementById('settings-last-fetched-' + id);
                if (lfCell) lfCell.textContent = lastFetched ? lastFetched.substring(0, 16) : '—';
                btn.textContent = '✅ ' + articles.length;
                btn.style.color = '#155724';
                if (articles.length === 0) {
                    resultsDiv.innerHTML = '<span style="color:var(--text-muted);">No new articles found in this feed.</span>';
                } else {
                    let html = '<div style="margin-bottom:0.25rem;font-weight:500;color:var(--ink);">📰 ' + articles.length + ' article(s) fetched, ' + summarized + ' summarized</div>';
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
                setTimeout(() => { resultsRow.style.display = 'none'; resultsDiv.classList.remove('active'); }, 15000);
                settingsResetTestBtn(id, btn, resultsRow, false);
                return;
            }
            attempts++;
            if (attempts < maxAttempts) { setTimeout(poll, 2000); }
            else { resultsDiv.innerHTML = '<span style="color:var(--text-muted);">⏱ Timed out. Check Admin panel.</span>'; settingsResetTestBtn(id, btn, resultsRow); }
        } catch(err) { resultsDiv.innerHTML = '<span style="color:#721c24;">❌ Error polling status</span>'; settingsResetTestBtn(id, btn, resultsRow); }
    }
    poll();
}

function settingsResetTestBtn(id, btn, resultsRow, hideResults) {
    if (hideResults === undefined) hideResults = true;
    setTimeout(() => { btn.textContent = '🧪'; btn.disabled = false; btn.style.color = 'var(--text-muted)'; }, hideResults ? 500 : 3000);
}

// ── Restore collapsible state for settings-sources ──
(function() {
    if (localStorage.getItem('settings-settings-sources-open') === 'true') {
        const el = document.getElementById('settings-sources');
        const chevron = document.getElementById('settings-sources-chevron');
        if (el && chevron) { el.classList.remove('hidden'); chevron.textContent = '▼'; }
    }
})();
```

- [ ] **Step 3: Wire settings-sources into the existing toggleCollapsible function**

The existing `toggleCollapsible` function in `settings.html` only restores `'unified-sources'` and `'status-overview'`. Add `'settings-sources'` to the restore list:

Find the `forEach` block near the top of the settings script:
```javascript
['unified-sources', 'status-overview'].forEach(id => {
```
Change to:
```javascript
['settings-sources', 'unified-sources', 'status-overview'].forEach(id => {
```

- [ ] **Step 4: Verify template compiles**

```bash
python -c "from app.web.routes import templates; t = templates.get_template('settings.html'); print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Run test suite**

```bash
python -m pytest tests/ -x -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add app/web/templates/settings.html
git commit -m "feat: unified RSS + YouTube sources section in settings"
```
