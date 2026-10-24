# Pipeline simplification: single-pass summaries, leaner digest input

**Status:** proposed — not implemented on `main`. Experiment script + results are
throwaway (`.tmp/`). Date: 2026-10-24.

## 1. Why

The summarization pipeline still decomposes work the way it had to when the
summarizer ran on `gemma-4-31b-it` (16K TPM free tier, frequent `504`s). The
current model (`gemini-3.5-flash-lite`, ~1M input / 64K output) makes most of
that decomposition pure overhead:

- **Article map-reduce** (`rss_chunk` 4K-char chunks → `rss_reduce`) compresses
  the same article twice before the digest ever sees it. A 15K-char article is
  ~3.7K tokens — 0.4% of the context window.
- **Condensation** (~500 words/article) exists to fit the per-minute token
  budget. Current digest input is ~10K chars/day; the budget is 250K tokens.
- **Truncation** at `max_article_chars=15,000` silently drops content from
  **174 of 1,018 articles (17%)** before summarization.
- **Digest extract→merge** is *not* a context problem. It exists because a
  single pass over ~40 stories silently dropped ~8 while claiming full coverage
  (AGENTS §6.7). That is an enumeration/attention limit, not a window limit —
  so it is deliberately **out of scope** for this change until measured.

## 2. Measured baseline (local DB, 1,018 summarized articles)

| Metric | Value |
|---|---|
| RSS raw text | p50 8,184 / p90 22,266 / max 32,339 chars |
| YouTube transcript | p50 1,436 / p90 22,542 / max 48,846 chars |
| Articles > 4,000 chars (chunked) | 601 (59%) |
| Chunk calls | 2,455 (+ 601 reduce calls) |
| Calls per article | ~3.6 |
| Per day | 8.1 articles → ~19.5 chunk + 4.8 reduce calls |
| Digest input, condensed | avg 9,872 / max 37,415 chars/day |
| Digest input, uncondensed | avg 31,334 / max 72,944 chars/day |
| Max articles/day | 30 |

**22 Oct 2026 test day:** 6 RSS articles (71,232 chars, 18 chunks) + 1 YouTube
transcript (27,853 chars, 5 chunks).

## 3. Constraints (hard)

- Free tier: **250,000 TPM**, **13 RPM**, 480 RPD.
- Config enforces a buffer: `gemini_tpm_limit=230000`, `gemini_rpm_limit=13`.
- The limiter reserves `len(prompt)//4 + max_tokens` (`app/summarizer/llm.py`),
  shared across app + worker via SQLite.
- **Sustain-13-RPM rule:** each request should reserve **≤ 250,000 / 13 ≈
  19.2K tokens**, otherwise the limiter must pace below 13 RPM for that minute.

## 4. Per-request budget

| Stage | Input cap | `max_tokens` | Reserve | ×13 RPM |
|---|---|---|---|---|
| Article, typical | 8.2K chars | 6,144 | 8.2K | 107K |
| Article, p90 | 22.3K chars | 6,144 | 11.7K | 152K |
| Article, max (48.8K chars) | 50,000 chars | 6,144 | 18.3K | **238K ✅** |
| Digest extract | 3K chars (condensed) | 4,096 | 4.8K | 62K |
| Digest merge (condensed, worst day) | 37.4K chars | 16,384 | 25.7K | 1 call/day |
| Digest merge (uncondensed, worst day) | 72.9K chars | 16,384 | 34.6K | 1 call/day |

`max_tokens=6,144` is safe: the longest summary ever stored is 13,582 chars
(~3.4K tokens). The merge cap drops from 32,768 to 16,384 because the stored
digest is ~6.7K chars (~1.7K tokens); the 32K reservation just starves the window.

## 5. Proposed changes

### Phase 1 — single-pass article summaries (low risk)

- `_summarize_article`: one call per article, no chunking.
- `max_article_chars: 15,000 → 50,000` (covers the largest observed 48,846).
- `max_tokens=6,144` for article summaries.
- Keep a chunking path only as a safety valve for pathological inputs (>100K
  chars), which do not occur today.
- Archive `article/rss_chunk.md` and `article/rss_reduce.md` if the fallback is
  kept out of the main path; `youtube_reduce.md` likewise.
- Expected: better fact retention (one compression instead of two), ~3.6 → 1
  call/article, no 15K truncation.

### Phase 2 — drop condensation (low risk, measure)

- `_get_condensed_summary` returns the full summary; no `condense` call.
- Digest input grows from ~9.9K to ~31.3K chars/day (max 72.9K) — still ~18K
  tokens worst case, well under both the 1M window and the 250K TPM budget.
- Expected: fewer calls (one less per article), no extra lossy pass; risk is
  verbose articles dominating the digest.

### Phase 3 — single-pass digest (gated, NOT part of this experiment)

- Only if a dedicated coverage test shows parity with per-article extraction on
  both a light and a 30-article day.
- Requires a new prompt with an explicit story-inventory / coverage checklist,
  and a `max_tokens` ≥ 16K (a 30-article digest can exceed 8K output).
- Keep extract→merge if any stories are dropped.

## 6. Experiment on 2026-10-22

**Setup:** read-only snapshot of the VPS DB (`VACUUM INTO`), copied per variant;
`llm_rate_events` cleared; same model, prompt set, and temperature as production.

| Variant | Article stage | Condense | Digest stage |
|---|---|---|---|
| PRE | current map-reduce | yes | extract→merge |
| V1 | single-pass | yes | extract→merge |
| V2 | single-pass | no | extract→merge |

For each variant: re-summarize all 22 Oct articles (RSS + YouTube), then
regenerate both digests. Outputs + metrics saved per variant.

**Metrics**

- Per article: summary chars, compression ratio, and *recall vs raw text* of
  numbers/percentages, dates, and capitalised proper-noun tokens (crude but
  repeatable proxies for fact retention).
- Per digest: story-block count, headings, reference coverage, chars, and
  numeric recall against the day's article summaries.
- Ops: LLM calls, reserved tokens per minute (max), wall-clock, rate-limit waits.

**Acceptance gates**

1. No regression in numeric/date recall (allow −5% measurement noise).
2. Digest story-block count ≥ PRE and every source ref present.
3. No prompt errors, no 429s, 13 RPM never exceeded, TPM peak ≤ 250K.
4. ≥ 40% fewer LLM calls for the day.
5. Manual read: no missing story, no duplicated block, sections still coherent.

**Caveats:** `temperature=0.5` makes wording non-deterministic (see AGENTS
§6.16); one day / 6 articles is a small sample, so a second run is warranted if
any gate is borderline.

## 7. Rollout & rollback

1. Land Phase 1 behind a config flag (`single_pass_articles`), default off.
2. Run the 22 Oct experiment + one heavy day (≥ 20 articles).
3. Flip the default, regenerate nothing (new articles only); old digests stay.
4. Rollback = flip the flag; no schema or data migration involved.
5. Phase 2 is a separate flag (`skip_condense`) and a separate eval of digest
   quality, since it changes what the digest reads.

## 8. Risks

- **Long-context attention:** a 12K-token article is far below where this
  matters, but monitor summaries for "lost in the middle" omissions.
- **Summary length growth:** removing `reduce` makes summaries longer; verify
  the digest still respects its 32K output cap and section balance.
- **TPM bursts:** single-pass removes the 5-way parallel chunk burst, so pacing
  improves; the limiter remains the source of truth.
- **Cache layers:** changing summarization prompts does nothing to stored
  `summary_text`; changing condense does nothing until `condensed_summary` is
  nulled. The experiment resets both explicitly.
- **Prompt cache:** templates are cached per process; restarts required.

## 9. Out of scope

- Digest two-phase removal (Phase 3) — separate coverage experiment.
- Model change, prompt wording changes, Kindle/web rendering.
- Backfilling historical summaries/digests.

## 10. Results — 2026-10-22 experiment (4 variants)

Read-only VPS DB snapshot; 6 RSS articles (71,232 chars) + 1 YouTube transcript
(27,853 chars). Each variant re-summarized all 7 items and regenerated both
digests with the same model/prompts. `temperature=0.5`.

| Variant | Article stage | Condense | LLM calls* | Wall-clock | Peak TPM | RSS digest | Blocks | Num recall | Month recall |
|---|---|---|---|---|---|---|---|---|---|
| PRE | map-reduce | yes | 39 | 613 s | 113K | 27,741 ch | 23 | 0.34 | 0.67 |
| V1 | single-pass | yes | 22 | 365 s | 66K | 30,272 ch | 31 | 0.35 | 0.75 |
| **V2** | **single-pass** | **no** | **16** | **202 s** | **86K** | 29,375 ch | **30** | **0.41** | **0.75** |
| V3 | map-reduce | no | 33 | 328 s | 116K | 27,021 ch | 23 | 0.30 | 0.67 |

\*computed from code paths; `llm_usage_events` undercounts when the limiter
fails open (see §11).

**Article-level summaries** (recall vs the full raw text):

| Variant | Avg summary chars | Numeric recall | Month recall | Proper-noun recall |
|---|---|---|---|---|
| PRE | 7,666 | 0.719 | 0.889 | 0.589 |
| V1 | 3,262 | 0.687 | 0.807 | 0.433 |
| V2 | 2,984 | 0.631 | 0.674 | 0.411 |
| V3 | 7,666 (same path) | 0.719 | 0.889 | 0.589 |

### Findings

1. **The final digest does not need map-reduce.** V2 produced 30 story blocks vs
   PRE's 23, with equal-or-better recall of the day's numbers, months and proper
   nouns, in **one third of the wall-clock and 16 vs 39 calls**. V2 surfaced
   stories PRE missed (airport privatisation, strategic petroleum reserves,
   satellite tolling, Ditto, OpenAI–Google Cloud).
2. **Map-reduce enriches article-level summaries, not the digest.** PRE's
   summaries are 2.5× longer with higher recall — good for `/article/{id}` and
   the footnote cards — but that detail is discarded by the condense step before
   the digest sees it. V3 (keep map-reduce, drop condense) did **not** improve
   the digest, so the gain comes from single-pass + no-condense together, not
   from dropping condense alone.
3. **Trade-off:** single-pass summaries are shorter (avg 2,984 vs 7,666 chars).
   The current `article/rss_summary.md` prompt yields ~11% of source length on a
   26K-char article, whereas chunking yields ~50%. If article-page depth
   matters, the single-pass prompt needs a detail target (or a hybrid threshold),
   not just a bigger input cap.
4. **Over-splitting is back.** V2 produced two SBI data-leak blocks (one per
   source article). The merge prompt needs a dedupe rule if coverage grows.
5. **All variants stayed inside the quota**: peak reservations 66-116K tokens
   per minute vs the 250K limit, and ≤13 RPM (latency-bound, not throttle-bound).

### Recommendation

- **Do not ship Phase 1 alone as a quality win.** On this day it trades
  article-page depth for speed; the digest gain is real but mostly comes from
  the denser summaries + no condensation.
- **V2 is the strongest candidate**: single-pass + no condense, 3× faster, 30
  stories vs 23. Before shipping: (a) add a detail target to the single-pass
  prompt and re-measure article summaries, (b) add a dedupe rule to
  `digest/merge.md`, (c) repeat on a heavy day (≥20 articles) to check the 32K
  digest output cap and TPM peak.
- **Keep the extract→merge digest stage unchanged.**

## 11. Prerequisite defect found: rate limiter fails open on DB lock

During digest generation the main connection holds an open write transaction
(the `condensed_summary` cache update) across LLM calls. The limiter uses its
own connection, hits `database is locked` after the 5s busy timeout, logs
`Rate limiter table unavailable ... proceeding unthrottled`, and disables pacing
for the rest of the process (`app/summarizer/llm.py:161-168`). This is the same
write-lock pattern as the Kindle bug (§6.15) and it is a **quota-compliance
risk on heavy days**, independent of this plan.

- PRE, V1 and V3 all hit it; V2 (no condensation writes) did not.
- `llm_usage_events` also under-records calls when it happens (PRE recorded 31
  of 39 calls), so the usage table is not trustworthy for auditing while the
  defect exists.
- Fix before relying on the limiter for a no-condense pipeline: either commit
  after each condensed-summary write, or make the limiter retry / fail closed.

