# Sidebar UX Fixes — Design Spec

**Date:** 2026-07-04  
**Status:** draft  

## Overview

Three sidebar usability issues:

1. **Collapse flicker on VPS** — sidebar flashes expanded then collapses on page load due to JS reading localStorage after render.
2. **YouTube subnav unusable when collapsed** — hidden with `display: none !important`.
3. **Sources page belongs in Settings** — separate page is awkward; should be merged as a collapsible section.

---

## 1. Collapse Flicker Fix

### Problem
On high-latency connections (VPS), the sidebar renders in its expanded state. After JS runs, it reads `localStorage('sidebar-collapsed')` and collapses — causing visible flicker.

### Approach
Blocking `<script>` immediately after `<body>` that reads localStorage and applies `sidebar-collapsed` to the `<body>` element before the browser paints.

### Implementation
- Add a `<script>` block right after `<body>` (same pattern as the existing theme script at line 11-18).
- Read `localStorage.getItem('sidebar-collapsed')`.
- If `'true'`, add `sidebar-collapsed` class to `document.body`.
- Keep the existing JS at line 328-335 as redundant backstop (no harm in double-applying).

### Templates affected
- `app/web/templates/base.html` — add blocking script.

---

## 2. YouTube Subnav in Collapsed Sidebar

### Problem
CSS rule `.sidebar-collapsed #sidebar #youtubeSubnav { display: none !important; }` makes the YouTube subnav invisible. User can't navigate channels when the sidebar is collapsed.

### Approach
When sidebar is collapsed and user clicks YouTube, temporarily expand the sidebar full-width to reveal the subnav. Clicking outside or navigating collapses it again.

### Behavior
1. Sidebar is collapsed (64px, icons only).
2. User is on a YouTube page (the YouTube sidebar item is a subnav toggle, not a link).
3. User clicks the YouTube toggle.
4. Sidebar expands to full width (240px). Subnav is visible. Chevron toggle works as normal.
5. User clicks anywhere outside the sidebar → collapses back to 64px, subnav state preserved.
6. User clicks any nav link inside the sidebar → collapses back to 64px AND navigates.
7. User clicks the sidebar toggle button → stays expanded (moves to normal expanded state, localStorage persists).
8. If the user is NOT on a YouTube page, the YouTube item is a plain `<a href="/youtube">` link — clicking it navigates normally and the sidebar stays collapsed. No temporary-expand behavior needed.

### Implementation
- Remove the CSS rule that hides `#youtubeSubnav` in collapsed mode: `.sidebar-collapsed #sidebar #youtubeSubnav { display: none !important; }`
- Add click handler on YouTube item: if sidebar is collapsed, temporarily expand (remove class, restore on blur/outside-click).
- Add a `click-outside` listener on `document` that checks if sidebar is in "temporary-expanded" state and collapses it.
- Use a data attribute or class (e.g., `expanded-for-youtube`) to distinguish temporary expansion from user-toggled expansion, so the toggle button doesn't get confused.

### Templates affected
- `app/web/templates/base.html` — remove CSS rule, update JS.

---

## 3. Sources → Settings Migration

### Problem
The `/sources` page is a standalone page listing only RSS feeds. It feels disconnected — it should live inside Settings alongside YouTube channels. Additionally, it should also list YouTube channels for a unified view.

### Approach
- Add a new collapsible "📡 Sources" section to `settings.html`, positioned **above** "Unified Sources & Run".
- The section contains a unified table of all sources (RSS + YouTube) with add/edit/test/toggle/delete actions.
- `/sources` → 303 redirect to `/settings`.
- Remove "Sources" link from the sidebar nav.
- Keep existing "YouTube Channels" section unchanged (it's a quick-add focused section).

### New section design
```
📡 Sources  ▶  (collapsible, expanded by default on first visit)
  12 sources configured
  [+ Add Source button]

  Table:
  | Type    | Name          | Status  | Last Checked | Actions              |
  | RSS     | TechCrunch    | Active  | 2026-07-03   | 🧪 ✏️ ⏸ 🗑          |
  | YouTube  | @veritasium   | Active  | 2026-07-02   | ✏️ ⏸ 🗑 (no 🧪)   |
```

### Add Source form
- Single input for URL/handle (no separate feed_url/name/category/site_url for simplicity — name auto-detected on add, category optional)
- Actually, keep the existing form from `sources.html` since it already works and has name/category/site_url fields. The form detects: if input looks like a YouTube handle or channel URL, it creates a YouTube source; otherwise it creates an RSS source.

Wait — this is complex. The existing `/api/sources` endpoint only handles RSS. YouTube uses `/api/youtube/sources`. The form needs to conditionally route.

**Simpler approach**: keep RSS and YouTube add forms separate within the collapsible section. A small segmented control or two buttons: "Add RSS Feed" / "Add YouTube Channel". Each reveals its own form. This way the existing API endpoints work unchanged.

**RSS form** (from existing `sources.html`): URL, Name, Category, Site URL — same as current.
**YouTube form** (from existing `settings.html`): Handle or channel URL input.

### Table details
- **RSS actions**: 🧪 Test, ✏️ Edit, ⏸/▶ Toggle, 🗑 Delete
- **YouTube actions**: ✏️ Edit (edit name/inline), ⏸/▶ Toggle, 🗑 Delete
- Test (🧪) uses the existing polling logic from `sources.html`
- Edit opens inline edit fields (as in `sources.html`)
- Toggle uses existing PATCH endpoints
- Delete uses existing DELETE endpoints

### Sidebar nav change
- Remove `<a href="/sources" ...>📡 Sources</a>` from `base.html`.

### Route change
- `GET /sources` → 303 redirect to `/settings`.

### State persistence
- Collapsible state persisted in localStorage with key `settings-sources-open` (matching existing pattern for other collapsibles).

### Templates affected
- `app/web/templates/settings.html` — add "📡 Sources" collapsible section at top.
- `app/web/templates/base.html` — remove Sources nav link.
- `app/web/routes.py` — redirect `/sources` → `/settings`.

### Template not removed
- `app/web/templates/sources.html` kept (not deleted, just no longer linked). Could be cleaned up later.

---

## Verification

1. **Flicker fix**: Load a page on VPS with sidebar previously collapsed. Sidebar should render collapsed immediately, no flash.
2. **YouTube collapsed**: Collapse sidebar → click YouTube → sidebar expands showing subnav → click outside → collapses back.
3. **Sources in settings**: Navigate to `/settings` → see "📡 Sources" at top → expand → see combined RSS + YouTube table → add RSS feed → test feed → toggle → delete. Navigate to `/sources` → redirected to `/settings`. Sidebar no longer shows "Sources" link.
