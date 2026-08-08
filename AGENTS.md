# AGENTS.md — Project Context for AI Agents

This file exists so that a fresh agent session can pick up where the last one
left off without re-discovering the codebase. It captures architecture, known
issues, the fixes already implemented (and where), gotchas, and the deploy
workflow. **Read this before doing anything.**

Last updated: 2026-08-09 (session: digest format → flowing story paragraphs,
renderer heading fixes, regenerated Aug 4-8 digests, DB-copy deploy to VPS).

---

## 1. What This Project Is

A single-user **personal news aggregator** ("RSS Digest"). It scrapes RSS feeds
+ YouTube channels daily, summarizes every article via LLM (Gemini primary,
Groq/DeepSeek fallback), then produces a **daily digest** that renders as a web
page. Purpose: read the whole day's news in ~5 minutes; open an original
article if a story interests you.

Stack: Python, FastAPI (Jinja2), SQLite (single file, zero config),
APScheduler (daily job), Docker Compose (VPS), trafilatura + Playwright for
extraction. No Redis/Postgres/Celery — one process, one SQLite file.

## 2. Quick-Start Commands

```bash
# Local dev server (Windows PowerShell, from repo root)
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Tests — MUST use a custom basetemp on Windows (see Gotcha #4)
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider --basetemp "C:\Users\pc\AppData\Local\Temp\opencode\pytest-basetmp"

# Regenerate a specific date's digest (RSS + YouTube) with live LLM calls
.\.venv\Scripts\python.exe scripts\generate_date_digest.py --date 2026-08-04

# Summarize all raw articles, auto-regen digests for affected dates
.\.venv\Scripts\python.exe scripts\run_summarization_now.py
```

## 3. Folder Structure (what matters)

```
app/
  config.py            # Settings (env-driven). Many fixes live here.
  database.py          # SQLite schema, migrations, CRUD. Has condensed_summary column.
  main.py              # FastAPI entry + APScheduler.
  scraper/service.py   # run_scrape() — feed fetch + text extraction.
  scraper/feed_reader.py, article_extractor.py
  summarizer/service.py    # run_summarization() pipeline + digest generation.
  summarizer/llm.py        # call_llm(), rate limiter, retry/fallback logic.
  summarizer/chunker.py    # Map-Reduce chunking.
  web/routes.py            # FastAPI routes + markdown renderer.
  web/templates/           # index.html (digest page), etc.
  prompts/manager.py       # PromptManager loads .md prompt templates.
Main Architechture/prompts/   # ACTUAL prompt templates used (see §5).
  daily_digest.md, youtube_digest.md, condense_summary.md,
  single_summary.md, reduce_synthesis.md, chunk_summary.md, ...
scripts/                 # Dev/diagnostic helpers (committed).
  generate_date_digest.py  # regen digest for a date (RSS+YT) — live LLM.
  discover_date_articles.py
  run_summarization_now.py
  validate_digest_tokens.py
data/aggregator.db       # Local SQLite DB (gitignored).
migrations/              # Versioned SQL migrations (applied via migrate service).
tests/                   # pytest suite. 88 tests, all passing.
```

## 4. Architecture Notes

- **Daily pipeline** (single APScheduler job `daily_scrape_and_summarize`):
  1. scrape → store articles as `raw`
  2. summarize each raw article (status → `summarized`)
  3. detect "affected dates" (newly summarized + orphan + stale digests)
  4. regenerate digests for those dates
- **Article statuses**: `raw` → `summarizing` → `summarized` | `failed` |
  `raw (rate limited)`. Rate-limited articles are requeued as `raw`, NOT failed.
- **Digest generation** (`_generate_daily_digest` / `_generate_youtube_daily_digest`
  in `app/summarizer/service.py`):
  - Pulls articles for a date, builds condensed summaries, sends to LLM.
  - Converts `[N]` tags to clickable `[[N]](url)` source links.
  - Appends `## 📚 Sources` automatically (model must NOT write it).
- **`run_summarization`** is resumable: commits per-article, so an interrupted
  run (timeout/kill) leaves progress intact. Rerunning picks up the rest.

## 5. Prompt Templates (IMPORTANT)

Prompts are loaded from `Main Architechture/prompts/` by `app/prompts/manager.py`
(resolution order: creator/detail → bare name → built-in fallback). **If you
edit a prompt template, regenerate existing digests to see the effect** — old
digests keep their stored text.

- `daily_digest.md` — RSS digest. **UNUSED since the extract→merge refactor**
  (kept as reference). Former format (Aug 8):
  - `## Today's Highlights` (2-3 plain sentences, no tags)
  - `##` sections with emoji + plain-English titles
  - **one story per bullet**: bold headline + WHAT happened (names/numbers/
    dates) + WHY it matters + WHAT'S NEXT (if source gives one) — 3-5 sentences
  - `## 💡 Key Takeaway` (3-4 bullets)
  - Plain-English glosses for jargon on first use ("SEBI (India's market
    regulator)", "margin calls (demands from lenders for more collateral)")
  - Do NOT write the Sources section (appended by code)
- `digest_story_extract.md` — per-article extraction prompt (new Aug 8
  architecture). One small LLM call per article extracts ONLY that article's
  stories as **`**Short headline**` + flowing prose paragraph** blocks (natural
  prose covering what happened / why / relevance / what's next, no labels, no
  bullets), each ending with `[REF n]`. Guarantees full coverage (flash-lite was
  dropping ~8/40 stories when asked to enumerate everything in one pass).
- `digest_merge.md` — merge prompt. Takes the pre-extracted story blocks and
  ONLY groups them into `##` sections + writes Highlights/Key Takeaway. Keeps
  blocks verbatim (model must NOT reword/drop them). Consecutive blocks are
  separated by a blank line (paragraphs, NOT list items).
- `youtube_digest.md` — YouTube digest. Same two-phase extract→merge flow
  (uses digest_story_extract + digest_merge), topics attributed to creators
  (claim + reasoning + implication).
- `condense_summary.md` — ~500-word condensation per article (raised from
  150-200 words so the digest model sees richer source material), preserving all
  names/numbers/dates. Feeds the digest prompt.

## 6. Known Problems & Fixes Already Implemented (this session)

These are DONE — a fresh agent must know they exist and where, to avoid
"re-fixing" them or breaking them.

### 6.1 Condensation was producing truncated, useless digests ✅ FIXED
- **Problem**: The condensation step used the thinking model `gemma-4-31b-it`,
  which burns its entire output-token budget on internal reasoning. For
  short-output tasks it returned empty responses ~2/3 of the time, or the server
  returned `504 DEADLINE_EXCEEDED`. The code then fell back to a naive
  600-char prefix truncation of the full summary → digests lost detail.
- **Fix**:
  - `app/config.py`: added `gemini_condense_model = "gemini-3.1-flash-lite"`
    (fast, non-thinking model) used ONLY for condensation.
  - `app/summarizer/llm.py`: added `504`, `502`, `deadline`, `timed out`,
    `connection reset`, `service unavailable` to the retryable-error list.
  - `app/summarizer/service.py` `_get_condensed_summary()`: passes
    `model=settings.gemini_condense_model`; still falls back to truncation only
    if ALL providers fail.
- **Diagnostic detail**: `gemma-4-31b-it` + 8192 max tokens → 504 (server
  deadline). 2048 tokens → empty response (all budget consumed by `thought`
  parts). The `_extract_gemini_text()` helper skips `thought=True` parts.

### 6.2 Per-minute token budget overrun (free-tier 429s) ✅ FIXED
- **Problem**: parallel chunk-map + large reduce requests blew the per-minute
  input-token quota.
- **Fix** (`app/summarizer/llm.py`): added `TokenRateLimiter` (rolling window,
  shared across providers) gating every call; reduce phase groups sub-summaries
  so no single request exceeds the budget (`app/summarizer/service.py`).

### 6.3 The Hindu Evening Wrap articles missing / attributed wrong ✅ FIXED
- **Problem**: The Hindu Evening Wrap feed (via kill-the-newsletter.com email
  gateway) exposes items **1-2 days late**. The old 48h lookback window let
  them fall out before being fetched.
- **Fix**: `app/config.py` → `lookback_hours = 96`. Feed still only retains ~9
  recent entries, so items older than that are **unrecoverable** (e.g. the July
  31 Evening Wrap is permanently lost; it was never fetched).

### 6.4 Stale digests not regenerated when articles link late ✅ FIXED
- `app/config.py` → `stale_digest_window_days = 7` (was hard-coded 3 days).
- `app/summarizer/service.py` runs stale-digest detection each
  `run_summarization()`: finds summarized-but-unlinked articles within window
  and regenerates those dates' digests.

### 6.5 Digest format: dense prose → scannable bullets → flowing story paragraphs ✅ FIXED
- The Aug 4 digest was a wall of merged paragraphs (hard to scan), then an
  over-correction stripped all detail. Current format (see §5): each story is a
  **`**short headline**` + flowing 3-5 sentence paragraph** (what/why/matters/
  next woven into natural prose, concrete names/numbers/dates, plain-language
  glosses). Applied to both RSS and YouTube prompts.

### 6.6 Digest capacity: 8192-token output cap → ~50-article headroom ✅ FIXED
- **Problem**: the digest is ONE LLM call with a hardcoded `max_tokens=8192`
  (service.py). At ~342 tokens of output per story, that capped out around
  20 articles; 50+ silently truncated (the Aug 7 6-article digest was already
  riding at ~8,180 tokens).
- **Fix**:
  - `app/config.py`: added `gemini_digest_model = "gemini-3.1-flash-lite"`
    (fast, non-thinking; 1M input / 64K output context) and
    `llm_digest_max_output_tokens = 32768`; raised
    `llm_input_tokens_per_min` to 200000 (flash-lite free tier = 250K TPM).
  - `app/summarizer/service.py`: both `_generate_daily_digest` and
    `_generate_youtube_daily_digest` now pass
    `model=model or settings.gemini_digest_model` and
    `max_tokens=settings.llm_digest_max_output_tokens`.
- **Headroom (measured)**: input = 912 template + ~370/article; output =
  ~342/article + ~300 overhead. 50 articles → input 19.6K / output 17.4K —
  comfortable. 80 articles OK. ~150 is where the 32K output cap binds.
- **Coverage guarantee**: `daily_digest.md` has a STEP 0 Story Inventory +
  STEP 3 Coverage Check (flash-lite dropped stories without it). The digest
  model still occasionally folds a minor item into a related bullet.

### 6.7 Digest architecture: single-pass → per-article extract + merge ✅ FIXED
- **Problem**: a single LLM pass over all articles could not reliably enumerate
  every story. On the 5-article Aug 4 digest (~40 stories), flash-lite dropped
  ~8 stories and did not notice (its self-check declared "none missing").
- **Fix** (`app/summarizer/service.py` + two new prompts):
  - **Phase 1** `digest_story_extract.md`: one small call per article extracts
    that article's stories as **`**headline**` + flowing paragraph** blocks,
    tagged `[REF i]`. Each call only enumerates one summary (2-15 stories) →
    reliable. On extraction failure, falls back to a single `- **title**` bullet
    with the condensed summary so the article is never silently dropped.
  - **Phase 2** `digest_merge.md`: one call groups the pre-extracted blocks
    into sections + writes Highlights/Key Takeaway. Blocks must be kept
    verbatim (prompt forbids rewording/dropping).
  - Both RSS and YouTube digests use this flow. Old `daily_digest.md` /
    `youtube_digest.md` single-pass prompts are now unused (kept as reference).
  - Result: 50/50 stories covered on Aug 4 (was ~14-18 with drops).
- **Cost**: digest generation is now N extract calls + 1 merge call. At 50
  articles that's 51 small calls (vs 1 big one) — within the 200K/min budget
  (each extract is small) but slower wall-clock.

### 6.8 Renderer: **bold** story headings misrendered as bullets ✅ FIXED
- **Problem**: a bold-only paragraph like `**Headline**` was misclassified as a
  **bullet list** by `_is_bullet_list` (`app/web/routes.py`), which treated any
  line starting with `*` as a bullet. `_clean_bullet` then stripped the leading
  `*` markers, leaving a dangling trailing `**` in the rendered output (e.g.
  "Abhijeet Dipke leads NEET-UG reform protests**").
- **Fix**: `_is_bullet_list` now only treats a line as a bullet when it starts
  with `- `, `* ` (marker + space), or `•`. A bare `**bold**` line renders as
  bold text instead.
- The stored digest text was always correct — this was purely a rendering bug.

### 6.9 Renderer: no visual gap between bold heading and body ✅ FIXED
- **Problem**: digests that stored the story heading and body WITHOUT a blank
  line between them (`**Headline**\ntext` — e.g. Aug 4) rendered as a single
  `<p>` joined with `<br>`, so the heading ran straight into the paragraph with
  no spacing. Digests that happened to have a blank line (Aug 5/7) showed the
  gap.
- **Fix** (`app/web/routes.py` `render_markdown`): a bold-only first line in a
  paragraph block is now rendered as its own `<p>` (the heading), with the
  remaining lines as a following `<p>` — giving consistent visual separation
  whether or not the source wrote a blank line.

## 7. Environment / Config (app/config.py)

Key settings (env-overridable via `.env`):
- `gemini_model = gemma-4-31b-it` (thinking model — for article summaries)
- `gemini_condense_model = gemini-3.1-flash-lite` (non-thinking — for condensation)
- `gemini_digest_model = gemini-3.1-flash-lite` (non-thinking — for the daily/youtube digest)
- `llm_max_output_tokens = 8192` (article summaries)
- `llm_digest_max_output_tokens = 32768` (single digest call — ~50-article headroom)
- `llm_input_tokens_per_min = 200000`, `rate_limit_window_seconds = 60`
- `lookback_hours = 96`, `stale_digest_window_days = 7`
- `condense_target_chars = 3000` (~500 words; also skip-if-short threshold + fallback),
  `max_article_chars = 15000`, `chunk_size = 4000`
- `scrape_cron_hour = 8` (VPS `.env` sets `SCRAPE_CRON_HOUR=08`, `MINUTE=00` →
  **daily 08:00 IST**)

Providers fallback chain: `_ALL_PROVIDERS = ["deepseek", "groq", "gemini"]`;
primary = `llm_provider`. `model=` override in `call_llm` is applied to Gemini
only (groq/deepseek ignore it).

## 8. Deployment (VPS)

- **VPS**: `root@188.245.161.234`, project at `/opt/personal-website`, Docker
  Compose. Services: `rss-aggregator` (app), `personal-website-worker-1`
  (worker), one-shot `migrate`.
- **DB is separate per machine. NEVER copy the local DB over the VPS DB in
  normal operation** (README warning). Exceptions are deliberate, with backup.
  This was done on **2026-08-09** to ship the regenerated Aug 4-8 digests
  without re-running LLM calls on the VPS: stopped containers → backed up VPS DB
  → `scp` local `data/aggregator.db` over the VPS one → started containers.
- **Deploy code flow**:
  1. Commit + push locally: `git push origin main`
  2. SSH to VPS: `cd /opt/personal-website && git pull origin main`
  3. `docker compose up -d --build` (rebuilds; runs migrate first) — OR if only
     `Main Architechture/` or `app/` bind-mounted files changed: `docker compose
     restart app worker` is enough.
  4. Verify: `curl -s http://127.0.0.1:8000/health` (→ `{"status":"ok"}`)
- **Regenerate a date's digest on the VPS** (new format):
  `docker compose exec -T app python scripts/generate_date_digest.py --date 2026-08-04`
- **DB backups on VPS**:
  - `data/aggregator.db.bak-20260808-213533` (before the last migration)
  - `data/aggregator.db.bak-20260809-pre-db-copy` (before the DB-copy deploy)
- **Windows → VPS automation**: SSH password auth needs `SSH_ASKPASS` + a temp
  askpass script; see Gotcha #6. There is no SSH key set up.

## 9. Gotchas (Windows / this repo)

1. **PowerShell has no `<` redirection.** Pipe scripts into ssh instead:
   `$script | ssh root@... "python3"`.
2. **PowerShell + nested quotes** breaks inline `python -c` with quotes — write a
   temp `.py` file and pipe it.
3. **DB file locking**: a running uvicorn `--reload` holds `data/aggregator.db`;
   stop it before heavy DB ops if you hit "database is locked".
4. **pytest temp-dir PermissionError on Windows**: always run with
   `--basetemp "C:\Users\pc\AppData\Local\Temp\opencode\pytest-basetmp"` (a stale
   `pytest-of-pc` dir gets access-denied otherwise).
5. **`gemma-4-31b-it` is a thinking model** — do not give it short-output tasks
   with small token budgets (empty responses). Use the condense model for that.
6. **SSH password automation on Windows**: create a temp `vps-pass.txt` +
   `vps-askpass.cmd` that `type`s it, set `SSH_ASKPASS` / `SSH_ASKPASS_REQUIRE=
   force` / `DISPLAY=localhost:0`, then run `ssh`/`scp`. **DELETE the temp files
   immediately after** (credential hygiene — see §10).
7. **Digest regeneration for dates outside the stale window** won't happen
   automatically; use `scripts/generate_date_digest.py --date <date>`.
8. **`docker compose start` re-runs the one-shot `migrate` service** (it's part
   of the compose file with `restart: no`; `start` starts every defined
   container). That's fine — migrate is a no-op when no migrations are pending —
   but don't be surprised by the `migrate` container appearing in `docker ps`
   after a `docker compose start app worker`.

## 10. Security / Credential Hygiene (IMPORTANT)

- **Never** log, commit, or store the VPS SSH root password or API keys.
- Temp askpass/password files must be deleted after use (they already are).
- The user reuses one string for both VPS **root SSH** and the web **admin
  panel** (`WEB_PASSWORD` in `.env`) — flagged as a risk; recommend separating
  them. Web admin is exposed on port 8000.
- `.env` is gitignored and must stay that way. Watch that `WEB_PASSWORD` isn't
  pushed if `.env` is ever force-added.

## 11. Current Data State (as of 2026-08-09)

- Local DB: 591 articles, 69 daily digests, 26 YouTube digests. **Identical DB
  now also on the VPS** (shipped via DB-copy deploy on 2026-08-09 — see §8).
- **Aug 4-8 digests regenerated** (2026-08-09) in the current flowing-story
  format: Aug 4 (5 articles, 24.4K chars), Aug 5 (7 articles, 27.8K), Aug 6
  (6 articles, 24.7K), Aug 7 (6 articles, 27.3K), Aug 8 (3 articles, 10.8K).
  Aug 8's digest previously had only 1 article; regeneration picked up all 3
  summarized articles.
- All 4 digests verified rendering on the live site (no dangling `**`, proper
  bold headings, heading/body gap) both locally and on the VPS.
- July 31 has 1 RSS + 1 YouTube digest. Some older June/July articles are
  `summarized` but not linked to digests (pre-existing data inconsistency
  outside the stale window — left alone).
