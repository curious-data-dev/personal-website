# TOC & Sources Sidebar UI Refinement — Design Spec

**Date:** 2026-07-04
**Status:** Approved

## Overview

Refine the right sidebar's Table of Contents and Sources sections for a more polished, integrated appearance. Two changes: collapsible TOC hierarchy and card-style visual separation.

## Collapsible TOC

### Behavior
- **Default:** h3 subheadings hidden (collapsed). Only h2 headings visible on load.
- **Toggle:** Clicking an h2 heading expands/collapses its child h3 entries.
- **Chevron:** `▸` on collapsed groups, `▾` on expanded groups.
- **Auto-expand:** If the scroll-spy detects the active heading is a collapsed h3, its parent h2 group auto-expands.

### Structure
TOC entries are grouped: each h2 plus its following h3 siblings form a group.

```
📑 On this page
┌──────────────────────────────────┐
│ ▸ Today's Highlights             │
│ ▾ Markets                        │
│     Tech Sector Analysis         │
│     Crypto Roundup               │
│ ▸ World                          │
└──────────────────────────────────┘
```

### Transition
- CSS `max-height` transition on the h3 container for smooth expand/collapse
- 200ms duration, ease-in-out

## Card-Style Visual Separation

### Design
Both TOC and Sources are wrapped in card containers:
- `border border-gray-200 dark:border-slate-700 rounded-lg` — subtle outline style
- No background fill (transparent/inherits sidebar background)
- `0.5rem` gap between TOC card and Sources card

### TOC Card
- `📑 On this page` header (small caps) at top of card
- Collapsible heading groups inside
- Padding: `p-3`

### Sources Card
- `📡 Sources` header inside the card
- Numbered list of citation links
- Padding: `p-3`

### Before/After

**Before:** Continuous list with headers, border-top separator
```
📑 On this page
  Today's Highlights
  Markets
    Tech Sector
  World
──────────────────────
📡 Sources
[1] Article → ...
```

**After:** Two distinct cards
```
┌──────────────────────┐
│ 📑 On this page      │
│ ▸ Today's Highlights │
│ ▾ Markets            │
│     Tech Sector      │
│ ▸ World              │
└──────────────────────┘

┌──────────────────────┐
│ 📡 Sources           │
│ [1] Article → ...    │
│ [2] Another → ...    │
└──────────────────────┘
```

## No Changes To
- Backend extraction logic (`extract_toc`, `extract_citations`)
- Route handlers
- Database
- Article/digest page templates

## Files to Change
- `app/web/templates/base.html` — TOC HTML structure, CSS, JS toggle logic
