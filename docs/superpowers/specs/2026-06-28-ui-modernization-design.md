# UI Modernization Design

**Date:** 2026-06-28
**Status:** Design approved

## Overview

Modernize the Media Hub UI from custom CSS to a Minimal/SaaS aesthetic using Tailwind CSS, applied page-by-page. The goal is a cleaner, airier, more polished look with refined typography, better spacing, and subtle micro-interactions.

## Stack Change

- **Remove:** All custom CSS in `app/web/static/style.css` (gradually, as pages convert)
- **Add:** Tailwind CSS v4 via standalone CLI binary (no npm, no PostCSS)
  - Input: `app/web/static/input.css` with `@import "tailwindcss";` and custom `@theme` overrides
  - Output: `app/web/static/output.css`
  - Build: `tailwindcss -i app/web/static/input.css -o app/web/static/output.css --watch`
- **Add:** Inter font from Google Fonts CDN (one `<link>` in `<head>`)
- **Keep:** Inline `<script>` for dark mode toggle and sidebar toggle (no JS framework)

## Design System

### Colors

**Light mode:**
| Token | Hex | Tailwind Mapping |
|---|---|---|
| Background | `#fafafa` | `bg-gray-50` (Tailwind default) |
| Surface (cards, sidebar) | `#ffffff` | `bg-white` |
| Foreground (primary text) | `#171717` | `text-gray-900` |
| Muted (secondary text, captions) | `#737373` | `text-gray-500` |
| Border | `#e5e5e5` | `border-gray-200` |
| Accent | `#2563eb` | `text-blue-600` / `bg-blue-600` |
| Accent-subtle (hover bg) | `#eff6ff` | `bg-blue-50` |

**Dark mode:** Use Tailwind's `dark:` variants — `dark:bg-slate-900`, `dark:bg-slate-800`, `dark:text-white`, `dark:text-slate-400`, `dark:border-slate-800`, `dark:text-blue-400`.

### Typography

- **Font family:** Inter (Google Fonts), with system-ui fallback
- **Heading scale:** `text-2xl` to `text-3xl` for page titles, `text-xl` for card titles
- **Body:** `text-base` (16px), `leading-relaxed`
- **Meta/captions:** `text-sm`, `text-gray-500`
- **Digest content:** `font-serif` with `text-base` and generous `leading-relaxed`

### Spacing

- Content max-width: `max-w-3xl` (768px)
- Section vertical rhythm: `space-y-6` to `space-y-8`
- Card padding: `p-6` to `p-8`

### Corners & Shadows

- Cards: `rounded-xl shadow-sm border border-gray-100 dark:border-slate-800`
- Smaller elements (pills, buttons): `rounded-lg` or `rounded-full`
- Hover lift: `hover:shadow-md hover:-translate-y-0.5 transition-all`

### Micro-interactions

- All interactive elements: `transition-all duration-200`
- Cards: `hover:shadow-md hover:-translate-y-0.5`
- Buttons: `active:scale-95`
- Links: color transition + `hover:underline`

## Phase 1: Setup

1. Download Tailwind CSS standalone CLI
2. Create `app/web/static/input.css` with:
   - `@import "tailwindcss";`
   - `@theme` block with custom colors, font family (if needed beyond Tailwind defaults)
3. Add Inter font `<link>` to `base.html`
4. Add `<link rel="stylesheet" href="/static/output.css">` to `base.html`
5. Add Tailwind build/watch command to project scripts

## Phase 2: base.html + Sidebar

Convert the shared layout shell first since every page inherits from it.

**Sidebar (desktop):**
- `w-60` (240px), `bg-white dark:bg-slate-900`, right border `border-r border-gray-200 dark:border-slate-800`
- Brand: larger "Media Hub" text in Inter bold, with collapsed state (`w-16`, 64px, icons only, centered)
- Nav links: icon + label, `rounded-lg px-3 py-2.5`, active = `bg-blue-50 text-blue-600 dark:bg-blue-950 dark:text-blue-400`, inactive = `text-gray-500 hover:text-gray-900 hover:bg-gray-50 dark:hover:text-white dark:hover:bg-slate-800`
- Bottom group (settings + theme toggle): separated by `border-t border-gray-100 dark:border-slate-800`, same link style
- Collapse toggle: hamburger icon button, persists to localStorage as currently
- YouTube subnav: stays collapsible, matches nav link style but smaller, indented

**Mobile (≤768px):**
- Hamburger button in a slim top bar (`h-14`)
- Sidebar slides in as an overlay drawer from left (`fixed inset-y-0 left-0 z-50 w-72`)
- Backdrop overlay fades in behind drawer
- Close with X button or clicking backdrop
- Same nav content inside drawer

**Theme toggle script updates:**
- Replace emoji-based toggle with a sun/moon SVG icon pair
- Keep localStorage persistence and `data-theme` attribute

## Phase 3: Daily Digest (index.html)

**Date Navigation:**
- Slim row: prev arrow (pill) / date heading (`text-2xl font-bold`) / next arrow (pill)
- Arrows: `rounded-full px-3 py-1.5 border border-gray-200 dark:border-slate-700 hover:border-blue-300` transition
- Disabled: `opacity-40 pointer-events-none`

**Status Bar:**
- Replace bordered box with a horizontal strip of metric pills
- Each pill: `rounded-full px-3 py-1 bg-gray-50 dark:bg-slate-800 text-sm text-gray-500`, icon + label + value
- Digest-ready indicator: green dot (`w-2 h-2 rounded-full bg-green-500 inline-block`)

**Digest Card:**
- `p-8 rounded-xl shadow-sm border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900`
- Digest heading inside card
- Content: `font-serif leading-relaxed text-gray-800 dark:text-gray-200`
- Footer: article/source count, separated by `border-t border-gray-100 dark:border-slate-800 pt-4 mt-6`

**Articles in Digest (expandable):**
- `<details>` styled with Tailwind: summary as a clickable pill/badge
- Expanded list: each article row — link + source badge, no internal borders, just `py-2`

**Empty State:**
- Large emoji (`text-6xl`)
- Message in `text-gray-500`
- Action suggestion in smaller text

## Phase 4: Article Page (article.html)

- Breadcrumb: `text-sm text-gray-400 hover:text-blue-600` links, `text-gray-300` separators
- Title: `text-2xl font-bold text-gray-900 dark:text-white`
- Meta row: source badge pill + date + reading time, all `text-sm text-gray-500`
- Summary card: `bg-blue-50/50 dark:bg-blue-950/20 border-l-4 border-blue-500 rounded-r-xl p-6`
- Action buttons: "Read original →" = `rounded-lg bg-blue-600 text-white px-4 py-2`, "← Back" = `rounded-lg border border-gray-200 px-4 py-2`
- Error state: `bg-red-50 dark:bg-red-950/20 border-l-4 border-red-500 rounded-r-xl p-4 text-red-700 dark:text-red-300`

## Phase 5: History Page (history.html)

- Year tabs: horizontal scrollable row of `rounded-full` pills, active = `bg-blue-600 text-white`
- Month selector: Tailwind-styled `<select>`
- Grid: `grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4`
- Each card: `rounded-xl shadow-sm border border-gray-100 bg-white dark:bg-slate-900 p-5 hover:shadow-md hover:-translate-y-0.5 transition-all`
- Card content: date (`text-xs text-gray-400`), title (`font-semibold text-gray-900 dark:text-white`), stats row, excerpt (`line-clamp-3 text-sm text-gray-500`)

## Phase 6: YouTube Page (youtube.html + youtube_history.html)

- Header: date + channel context, cleaner layout
- Channel pills row: `rounded-full` pills, active = `bg-blue-600 text-white`
- Video footnotes: collapsible toggle with smooth Tailwind transitions
- Footnote rows: cleaner spacing, channel and duration on right side in muted text
- Watch button: `rounded-lg bg-red-600 text-white px-3 py-1.5 hover:bg-red-700` pill with ▶ icon
- Mobile: channel pills visible as scroll row

## Phase 7: Sources Page (sources.html)

- Table: `rounded-xl border border-gray-200 dark:border-slate-800 overflow-hidden`
- Headers: `bg-gray-50 dark:bg-slate-800 text-xs uppercase text-gray-500 px-4 py-3`
- Rows: `border-t border-gray-100 dark:border-slate-800 hover:bg-gray-50/50 dark:hover:bg-slate-800/50`
- Status badges: `rounded-full text-xs px-2 py-0.5`, active = `bg-green-100 text-green-700`, inactive = `bg-red-100 text-red-700`

## Phase 8: Settings Page (settings.html)

- Form fields: `rounded-lg border border-gray-200 dark:border-slate-700 px-3 py-2 focus:ring-2 focus:ring-blue-500 focus:border-blue-500`
- Buttons: primary = `bg-blue-600 text-white rounded-lg px-4 py-2 hover:bg-blue-700`, secondary = `border border-gray-200 rounded-lg px-4 py-2`, danger = `border-red-300 text-red-600 rounded-lg px-4 py-2 hover:bg-red-50`
- Table: same styling as Sources table

## Phase 9: Final Cleanup

- Remove all custom CSS from `style.css` once all pages converted
- Remove old CSS `<link>` from `base.html`
- Verify dark mode works across all pages
- Verify responsive behavior on mobile/tablet breakpoints
- Verify all interactive elements (sidebar toggle, theme toggle, YouTube subnav, footnotes) work correctly

## Non-Goals

- No JavaScript framework (no React, Vue, Alpine, htmx). This is a server-rendered Flask app.
- No design changes to functionality — this is purely visual
- No changes to the Python backend
- No changes to the database or data model
