# Refresh-slot timing and D-1 coverage — open question

**Status:** note for later. No action required now.
**Date:** 2026-10-27
**Current state:** VPS daily run moved from 08:00 → **06:45 IST** on 2026-10-27
(commit `903d806`, config only: `SCRAPE_CRON_HOUR=06`, `SCRAPE_CRON_MINUTE=45`
in `/opt/personal-website/.env`). Code default is still 08:00.

## Context

The daily run on day **D** does two things relevant here:

1. It scrapes and summarizes new articles, assigning each to
   `published_date_ist`.
2. It regenerates every *affected* digest date, then the Kindle phase sends the
   **D-1** digest (RSS + YouTube, if present).

So the digest a reader gets on day D is for day D-1, and the question is:
**how complete is D-1 at 06:45, and does moving the run earlier cause D-1
articles to be missed?**

## The problem

`published_at` and `fetched_at` are different things:

- `published_at` — the timestamp the source puts on the item.
- `fetched_at` — when our scraper first stored it. Because we scrape once a day,
  this is **quantised to the run time** (02:30 UTC / 08:00 IST, now 01:15 UTC /
  06:45 IST).

An item can have `published_date_ist = D-1` and first appear in our DB on D,
D+1, or even D+4. Consequences:

- Articles published on D-1 **after** the previous day's run are picked up on
  the D run. That is normal and desirable: it finalizes D-1.
- If an item becomes available in the feed only **between 06:45 and 08:00 on
  D**, a 06:45 run misses it; it is fetched on D+1, assigned back to D-1, and
  **updates the D-1 digest a day after the Kindle email was sent**.
- The same mechanism causes the older problem of a **D-2 (or older) digest**
  being updated later, because some feeds deliver 1-2 days late.

Measured over all daily digests: **40 of 148 (27%) were updated 2+ days after
their date**. That happens with the old 08:00 schedule too; the hour change is
not the cause.

## What the data shows (VPS DB, 2026-10-13 → 2026-10-26)

### A. D-1 articles: when they are first fetched

Lag = fetch date − `published_date_ist`. For D-1, "fetched on D" = lag 1.

| D-1 date | Articles in D-1 | First fetched on D (finalizing run) | First fetched D+1 or later |
|---|---|---|---|
| 13 Oct | 9 | 6 | 1 (CaspianReport, +4d) |
| 14 Oct | 8 | 5 | 2 (ThePrint +2d, Akshat +2d) |
| 15-18 Oct | 5-7/day | 4-7/day | 0 |
| 19 Oct | 8 | 0 | 0 |
| 20 Oct | 6 | 6 | 0 |
| 21 Oct | 9 | 6 | 1 (ThePrint +2d) |
| 22-25 Oct | 5-7/day | 1-5/day | 0 |
| 26 Oct | 2 | 0* | 0 |

\*today's 08:00 run had not happened when this was measured.

Publication hours of the "first fetched on D" set: **08:00-23:59 on D-1** —
i.e. at least ~7 h before a 06:45 run on D. If a feed publishes promptly, those
items are already in the feed at 06:45.

### B. The 06:45-08:00 window (the actual risk)

Articles *published* 07:00-08:00 on a day: **0-2/day**, always from the same
two feeds:

```
07:00        Finshots
07:14-07:46  Daily Brief - Zerodha
```

Every one of these belongs to **that same day**, not to D-1 (D-1 ended at
midnight). Across the last 7 days, **0** of the articles that finalize D-1 were
published in the 07:00-08:00 window.

The genuinely late feeds (the ones that cause age-2+ updates):

| Source | Articles | Same day | +1 day | +2 days |
|---|---|---|---|---|
| The Hindu – Evening Wrap | 142 | 5 | 136 | 1 |
| ThePrint Essential | 58 | 0 | 34 | **24** |
| Bloomberg India | 38 | 1 | 36 | 1 |
| Rundown AI | 45 | 1 | 43 | 1 |
| Akshat Shrivastava | 8 | 0 | 3 | **5** |

### C. What is *not* measurable from history

Because `fetched_at` is quantised to run times, we cannot tell whether an item
entered the feed at 02:00 or at 07:30 on D. Therefore:

- **Expected impact on D-1 at 06:45: ≈ 0**, based on publication times and feed
  behaviour.
- **Not provably 0.** An item delivered into the 06:45-08:00 hour would be
  missed, and the D-1 digest would be updated on D+1.

## Options (pick up later)

| Option | What it does | Cost / risk |
|---|---|---|
| **A. Feed probe** (recommended for certainty) | Fetch every feed at 06:45 and 08:00 for 3-5 days, record item GUID + first-seen, report D-1 items first seen in the 06:45-08:00 window | Read-only; no app change; needs a few days |
| B. Freeze stale digests | `stale_digest_window_days: 7 → 1` so only D-1 is regenerated; no more age-2+ updates | Drops late `+2d` articles (≈24 from ThePrint alone) — conflicts with "complete coverage" |
| C. Second daily run | e.g. 06:45 + 18:00, catches same-day late items and shrinks next-morning churn | Doesn't fix `+2d` feeds; more LLM calls |
| D. Fix late feeds | Evening Wrap email gateway, ThePrint, Rundown | Only way to get both completeness and stability; outside our code |

Current decision: keep 06:45 and accept the theoretical gap until Option A is
run. Kindle for D-1 now arrives ~06:50 instead of ~08:05.

## How to resume this later

1. Run the **feed probe** (Option A). Suggested shape:
   - read `sources.feed_url` for RSS sources;
   - fetch at 06:45 and 08:00 (optionally 07:00) for 3-5 days;
   - store `guid/link`, `published_at`, `first_seen_at` in a throwaway JSONL/SQLite
     (do **not** write to the production DB);
   - report, per day, D-1 items by first-seen bucket:
     `06:45-07:00`, `07:00-08:00`, `after 08:00`.
2. Decision rule:
   - 0 items in 06:45-07:00 for 5 days → close this note.
   - ≥1/day in 06:45-07:00 → either move to 07:00 or accept the 1-day-late
     update for those items.
   - If age-2+ updates are the real pain → evaluate Option B (window = 1) and
     quantify the dropped articles first.
3. If the schedule changes again: edit `SCRAPE_CRON_HOUR` /
   `SCRAPE_CRON_MINUTE` in the VPS `.env`, then `docker compose up -d`
   (env_file is read at container creation), and confirm the log line
   `Next scheduled run: ...`.

## References

- `app/main.py` — scheduler (`Asia/Kolkata`), `enqueue_scheduled_run()`.
- `app/orchestration.py` — scrape → summarize → digest → Kindle.
- `app/kindle/service.py` — sends D-1; content-hash dedupe.
- `app/config.py` — `stale_digest_window_days`, `lookback_hours`.
- `AGENTS.md` §6.3 (Evening Wrap delay), §6.12 (Kindle), §6.17 (pipeline),
  §7 (schedule).
