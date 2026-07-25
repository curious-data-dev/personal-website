# Smart Digest Regeneration After Scrape

**Date**: 2026-07-25
**Status**: approved

## Problem

Articles from sources like The Hindu Evening Wrap arrive with a delay — their `published_date_ist` falls on a date whose daily digest was already generated. The current orphan detection only creates digests for dates that have **no digest at all**. It never regenerates a digest that already exists but is missing articles.

This causes summarized articles to sit orphaned: present in the DB, visible in the article list, but absent from the daily digest.

## Design

After summarization completes, in addition to the existing "no digest" orphan check, also scan the **last 3 days** (today + yesterday + day-before-yesterday, in IST) for dates whose digest is **stale** — i.e., there are summarized articles for that date that aren't linked to the digest. Regenerate those digests.

### Key behaviors

- **No wasted LLM calls**: only regenerate a date if there are unlinked summarized articles.
- **3-day window**: computed in IST at run time. Dates outside the window are not auto-regenerated (manual regeneration still available from the admin panel).
- **Existing orphan detection unchanged**: dates with no digest at all continue to be caught and created.
- **No schema changes, no new files.** Modification is ~15 lines in `app/summarizer/service.py`.

### Logic flow

```
After summarizing articles:
  1. Existing: find dates with articles but NO digest → create digest
  2. NEW: for each of the last 3 IST dates:
     a. Does a digest exist for this date?
     b. Are there summarized articles for this date NOT linked to that digest?
     c. If both true → regenerate digest for this date
     d. If no unlinked articles → skip (no LLM call)
```

### Window calculation

```python
ist = timezone(timedelta(hours=5, minutes=30))
today_ist = datetime.now(ist).date()
window_dates = {
    today_ist.isoformat(),
    (today_ist - timedelta(days=1)).isoformat(),
    (today_ist - timedelta(days=2)).isoformat(),
}
```

### Stale digest query

```sql
SELECT DISTINCT a.published_date_ist AS d
FROM articles a
JOIN sources s ON s.id = a.source_id
WHERE s.source_type = 'rss'
  AND a.status = 'summarized'
  AND a.published_date_ist IN (?, ?, ?)
  AND EXISTS (
    SELECT 1 FROM daily_digests dg WHERE dg.date = a.published_date_ist
  )
  AND NOT EXISTS (
    SELECT 1 FROM digest_articles da
    JOIN daily_digests dg ON dg.id = da.digest_id
    WHERE da.article_id = a.id AND dg.date = a.published_date_ist
  )
```

## Scope

### In scope
- Extend `run_summarization()` in `app/summarizer/service.py` to detect and regenerate stale digests within a 3-day IST window.

### Out of scope
- Changing the scrape schedule or digest generation schedule.
- Adding per-source configuration for the window.
- UI changes (manual regeneration already exists in admin panel).
- Fixing existing orphaned articles (use `python -m app.backfill --regenerate-digests` or manual admin panel regeneration).

## Testing

- Unit test: mock DB with a stale digest (digest exists for date X, 3 articles summarized, only 2 linked) and verify `run_summarization` regenerates it.
- Unit test: mock DB where all articles are already linked — verify no regeneration triggered.
- Unit test: article outside the 3-day window — verify not triggered.
- Unit test: date with no digest at all — existing behavior still works.
