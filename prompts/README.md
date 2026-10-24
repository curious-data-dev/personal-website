# Prompts

Every LLM prompt that drives article summaries and the daily / YouTube digests
lives here. No prompt text should live in Python.

```
prompts/
  article/            per-article / per-video summarization (single pass)
  digest/             two-phase digest generation (extract -> merge)
  _legacy/            archived prompts — no code path uses these
```

The loader is `app/prompts/manager.py`. A logical name **is** the path inside
this folder minus `.md`: `"digest/merge"` → `prompts/digest/merge.md`.

## Active prompts

| Logical name | File | Stage | Placeholders | Model / max tokens |
|---|---|---|---|---|
| `article/rss_summary` | `article/rss_summary.md` | Summarize one RSS article in one call (input truncated to `max_article_chars=50000`) | `{text}` | `gemini_model` / `article_max_output_tokens=6144` |
| `article/youtube_summary` | `article/youtube_summary.md` | Summarize one video transcript in one call (structured output shown on the video page) | `{text}` | `gemini_model` / 6144 |
| `digest/rss_story_extract` | `digest/rss_story_extract.md` | RSS digest Phase 1: one call per article → story blocks (drives coverage) | `{ref_num}`, `{summary}` | `gemini_digest_model` / 4096 |
| `digest/youtube_story_extract` | `digest/youtube_story_extract.md` | YouTube digest Phase 1: one call per video, deeper write-up | `{ref_num}`, `{summary}` | `gemini_digest_model` / 4096 |
| `digest/merge` | `digest/merge.md` | Phase 2 for **both** digests: group blocks, write Highlights + Key Takeaway (drives structure) | `{date}`, `{story_bullets}` | `gemini_digest_model` / 32768 |

Prompt → model/max-token values are still set at the call sites in
`app/summarizer/service.py`; this table documents them.

## Archived prompts (`_legacy/`)

| File | Why it is here |
|---|---|
| `condense.md` | Removed: the digest now reads full article summaries (input is ~31K chars/day, well inside the window/TPM budget) |
| `rss_chunk.md`, `rss_reduce.md`, `youtube_reduce.md` | Removed: article summaries are single-pass (one call per article) |
| `daily_digest.md` | Old single-pass RSS digest, replaced by extract → merge |
| `youtube_digest.md` | Old single-pass YouTube digest, replaced by extract → merge |
| `podcast_summary.md` | No podcast pipeline exists |

Nothing loads these. They are kept for reference only.

## Changing a prompt

1. Edit the `.md` file.
2. **Restart `app` and `worker`.** Templates are cached in memory for the life
   of the process, so edits are invisible until restart (intentional).
3. Regenerate the digests you want to re-test:
   `python scripts/generate_date_digest.py --date YYYY-MM-DD [--skip-rss|--skip-youtube]`

Caching layers to remember when testing:

- `articles.summary_text` is stored per article. Changing a summarization prompt
  does nothing until that article is re-summarized.
- Digest rows store the final text; regenerate the date to see any change.

## Adding a prompt

1. Add the `.md` file under `article/` or `digest/` with the required
   `{placeholders}`.
2. Add a constant + entry to `ACTIVE_PROMPTS` in `app/prompts/manager.py`.
3. Add a row to the table above.
4. Add the placeholder set to `REQUIRED_PLACEHOLDERS` in `tests/test_prompts.py`.

Missing prompts raise `PromptNotFoundError` rather than silently falling back —
a renamed or deleted file fails the run loudly instead of changing digest
quality unnoticed.

## Conventions

- A logical name maps 1:1 to a file; no hidden resolution order.
- Templates are formatted with `str.format()`, so any literal brace must be
  escaped (`{{` / `}}`).
- `PROMPTS_DIR` overrides the folder (useful for tests / experiments).

## Why single-pass (2026-10-24)

Measured on 2026-10-22: single-pass article summaries + no condensation produced
30 digest stories vs 23 with map-reduce + condensation, with equal-or-better
fact recall, in 1/3 the wall-clock and 16 vs 39 calls. Every per-minute token
peak stayed under 116K vs the 250K free-tier limit. Full write-up:
`docs/superpowers/plans/2026-10-24-pipeline-simplification.md`.
