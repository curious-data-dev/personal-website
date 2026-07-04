# TOC & Sources Sidebar UI Refinement — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) to implement this plan task-by-task.

**Goal:** Refine the right sidebar with collapsible TOC hierarchy and card-style visual separation between TOC and Sources sections.

**Architecture:** HTML restructuring in `base.html` using Jinja2 grouping logic. Pure CSS for collapse transitions and card styling. Vanilla JS for toggle behavior and auto-expand on scroll-spy activation.

**Tech Stack:** Jinja2, CSS, vanilla JS — no backend changes

## Global Constraints

- No backend changes (no routes, no database, no extraction logic)
- Existing scroll-spy and smooth-scroll must continue working
- Dark mode must work with card borders via existing `dark:` convention
- Sidebar must still be hidden below `xl` breakpoint

---

### Task 1: Collapsible TOC + Card-style boxes + Toggle JS

**Files:**
- Modify: `app/web/templates/base.html` (TOC HTML section, CSS block, JS block)

**Interfaces:**
- Consumes: `toc: list[TocEntry]` with `.level` (2 or 3), `.text`, `.anchor`
- Produces: Collapsible grouped TOC, card-wrapped sections, toggle behavior

- [ ] **Step 1: Replace the TOC HTML with grouped structure**

Replace the current TOC HTML (from `{% if toc %}` through `{% endif %}` for the TOC block) with this grouped version:

```html
        {# ── Table of Contents ── #}
        {% if toc %}
        <div class="border border-gray-200 dark:border-slate-700 rounded-lg p-3 mb-2">
            <h4 class="text-xs font-semibold uppercase tracking-wider text-gray-400 dark:text-slate-500 mb-2 px-1">📑 On this page</h4>
            <nav class="flex flex-col gap-0.5" id="tocNav">
            {% set ns = namespace(current_h2=none, h3s=[]) %}
            {% for entry in toc %}
                {% if entry.level == 2 %}
                    {% if ns.current_h2 is not none %}
                        {# Close previous group #}
                        <button class="toc-group-toggle flex items-center gap-1 w-full text-left rounded-md px-2 py-1 text-sm font-medium text-gray-500 hover:text-blue-600 hover:bg-gray-50 dark:text-slate-400 dark:hover:text-blue-400 dark:hover:bg-slate-800 transition-colors"
                                data-toc-group="{{ ns.current_h2.anchor }}" aria-expanded="false">
                            <span class="toc-chevron text-xs flex-shrink-0">▸</span>
                            <span class="flex-1">{{ ns.current_h2.text | e }}</span>
                        </button>
                        <div class="toc-h3-group hidden ml-3" data-toc-parent="{{ ns.current_h2.anchor }}">
                        {% for h3 in ns.h3s %}
                            <a href="#{{ h3.anchor }}" class="toc-link block rounded-md px-2 py-1 text-sm font-medium text-gray-500 hover:text-blue-600 hover:bg-gray-50 dark:text-slate-400 dark:hover:text-blue-400 dark:hover:bg-slate-800 transition-colors"
                               data-toc-target="{{ h3.anchor }}">{{ h3.text | e }}</a>
                        {% endfor %}
                        </div>
                        {% set ns.h3s = [] %}
                    {% endif %}
                    {% set ns.current_h2 = entry %}
                {% elif entry.level == 3 %}
                    {% set ns.h3s = ns.h3s + [entry] %}
                {% endif %}
            {% endfor %}
            {# Last group #}
            {% if ns.current_h2 is not none %}
                <button class="toc-group-toggle flex items-center gap-1 w-full text-left rounded-md px-2 py-1 text-sm font-medium text-gray-500 hover:text-blue-600 hover:bg-gray-50 dark:text-slate-400 dark:hover:text-blue-400 dark:hover:bg-slate-800 transition-colors"
                        data-toc-group="{{ ns.current_h2.anchor }}" aria-expanded="false">
                    <span class="toc-chevron text-xs flex-shrink-0">▸</span>
                    <span class="flex-1">{{ ns.current_h2.text | e }}</span>
                </button>
                <div class="toc-h3-group hidden ml-3" data-toc-parent="{{ ns.current_h2.anchor }}">
                {% for h3 in ns.h3s %}
                    <a href="#{{ h3.anchor }}" class="toc-link block rounded-md px-2 py-1 text-sm font-medium text-gray-500 hover:text-blue-600 hover:bg-gray-50 dark:text-slate-400 dark:hover:text-blue-400 dark:hover:bg-slate-800 transition-colors"
                       data-toc-target="{{ h3.anchor }}">{{ h3.text | e }}</a>
                {% endfor %}
                </div>
            {% endif %}
            {# h2 entries with no h3 children: still render as a button for consistency #}
            {% if ns.current_h2 is none and toc|length > 0 and toc[0].level == 2 %}
                {# Already handled in the loop above #}
            {% endif %}
            {# Edge case: toc with only h2 entries and no h3s #}
            {% if ns.current_h2 is none %}
                {% for entry in toc %}
                    {% if entry.level == 2 %}
                    <a href="#{{ entry.anchor }}" class="toc-link block rounded-md px-2 py-1 text-sm font-medium text-gray-500 hover:text-blue-600 hover:bg-gray-50 dark:text-slate-400 dark:hover:text-blue-400 dark:hover:bg-slate-800 transition-colors"
                       data-toc-target="{{ entry.anchor }}">{{ entry.text | e }}</a>
                    {% endif %}
                {% endfor %}
            {% endif %}
            </nav>
        </div>
        {% endif %}
```

- [ ] **Step 2: Replace the Sources HTML with card wrapper**

Replace the Sources block:

```html
        {# ── Sources ── #}
        {% if sources %}
        <div class="border border-gray-200 dark:border-slate-700 rounded-lg p-3">
            <h4 class="text-xs font-semibold uppercase tracking-wider text-gray-400 dark:text-slate-500 mb-2 px-1">📡 Sources</h4>
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
```

- [ ] **Step 3: Add collapse/expand CSS transitions**

Add inside the existing `<style>` block, after the `.toc-link-active` rules:

```css
        /* ── TOC collapsible groups ── */
        .toc-h3-group {
            overflow: hidden;
            max-height: 0;
            transition: max-height 0.2s ease-in-out;
        }
        .toc-h3-group.expanded {
            max-height: 20rem; /* enough for several h3 items */
        }

        .toc-group-toggle[aria-expanded="true"] .toc-chevron {
            transform: rotate(90deg);
            transition: transform 0.15s ease;
        }
        .toc-chevron {
            transition: transform 0.15s ease;
        }
```

- [ ] **Step 4: Add toggle JS to the existing script block**

Add BEFORE the TOC scroll-spy JS (which depends on `.toc-link` elements being present):

```javascript
        // ── TOC group toggle ──
        (function() {
            var toggles = document.querySelectorAll('.toc-group-toggle');
            toggles.forEach(function(toggle) {
                toggle.addEventListener('click', function() {
                    var group = this.getAttribute('data-toc-group');
                    var container = document.querySelector('.toc-h3-group[data-toc-parent="' + group + '"]');
                    if (!container) return;
                    var expanded = container.classList.contains('expanded');
                    if (expanded) {
                        container.classList.remove('expanded');
                        this.setAttribute('aria-expanded', 'false');
                    } else {
                        container.classList.add('expanded');
                        this.setAttribute('aria-expanded', 'true');
                    }
                });
            });
        })();
```

- [ ] **Step 5: Update scroll-spy to auto-expand parent when hidden h3 is active**

Find the `updateActive()` function in the existing scroll-spy JS. After the line that sets `activeLink.classList.add('toc-link-active')`, add auto-expand logic:

```javascript
            // Auto-expand parent group if active link is a collapsed h3
            function expandParentIfNeeded(link) {
                var parent = link.closest('.toc-h3-group');
                if (parent && !parent.classList.contains('expanded')) {
                    parent.classList.add('expanded');
                    var groupAnchor = parent.getAttribute('data-toc-parent');
                    var toggle = document.querySelector('.toc-group-toggle[data-toc-group="' + groupAnchor + '"]');
                    if (toggle) toggle.setAttribute('aria-expanded', 'true');
                }
            }
```

Then in the `updateActive()` function, right before `if (activeLink) activeLink.classList.add('toc-link-active')`, add:
```javascript
            if (activeLink) expandParentIfNeeded(activeLink);
```

- [ ] **Step 6: Remove old border-top separator from sidebar CSS**

In the CSS block, find and remove the `.border-t` references that were previously used to separate TOC from Sources (if any were inline). The card wrappers now handle separation.

- [ ] **Step 7: Verify — reload page**

```bash
# Restart uvicorn if needed
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `http://localhost:8000/digest/2026-07-03`. Verify:
- TOC shows h2 headings with `▸` chevrons
- Clicking an h2 reveals its h3 children with `▾` (rotated) chevron
- TOC and Sources are in separate rounded cards
- Dark mode shows correct border colors
- Scroll-spy still highlights the active heading
- Auto-expand: scrolling to a collapsed h3 heading expands its parent

- [ ] **Step 8: Run tests**

```bash
python -m pytest tests/ -q
```

Expected: all 60 tests pass (no backend changes).

- [ ] **Step 9: Commit**

```bash
git add app/web/templates/base.html
git commit -m "feat: collapsible TOC hierarchy and card-style sections in right sidebar"
```
