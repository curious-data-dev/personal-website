# YouTube Individual Video Summary Formatting

**Date:** 2026-06-28
**Status:** Approved — awaiting implementation plan

## 1. Problem

Individual YouTube video summaries have poor formatting compared to the daily YouTube digest. Two root causes:

1. **`article.html` doesn't render markdown** — uses a plain `split('\n\n')` + `<p>` loop, while the digest template uses `| markdown | safe`. Structured LLM output is displayed as raw text.

2. **`youtube_summary.md` prompt exists but is never used** — `_summarize_article()` always calls `single_summary` regardless of source type. The YouTube-specific prompt is dead code.

3. **Neither `single_summary.md` nor `youtube_summary.md` instructs the LLM to produce structured output** — no headings, sections, or bullet points. Compare: the digest prompt (`youtube_digest.md`) specifies `## Today's Highlights`, emoji-prefixed `##` sections, and `## 💡 Key Takeaways` with bullet points.

## 2. Scope

| Component | Changed? |
|---|---|
| Individual video summary LLM prompt (`youtube_summary.md`) | ✅ Rewrite with fixed-section structure |
| `_summarize_article()` routing logic | ✅ Route YouTube articles to `youtube_summary` prompt |
| Individual video page render (`article.html`) | ✅ Use `| markdown \| safe` filter |
| Migration: reset last 3 days of YouTube summaries | ✅ One-time SQL + code on deployment |
| YouTube daily digest prompt (`youtube_digest.md`) | ❌ Untouched |
| YouTube daily digest render (`youtube.html`) | ❌ Untouched |
| RSS article summaries (`single_summary.md`) | ❌ Untouched |

**Side effect:** Per-video footnote summaries in the YouTube digest card inherit the improved formatting since they display the same `summary_text` field.

## 3. Design

### 3.1 Prompt Structure

The new `youtube_summary.md` produces 4 fixed sections every time:

```
## 🎯 Main Argument
A concise paragraph capturing the video's core thesis — what the creator
is arguing for, explaining, or demonstrating.

## 📝 Supporting Points
The evidence, data, examples, and reasoning the creator uses. Write as
flowing prose (not a bullet list), covering each distinct point clearly.

## 🔮 Conclusions / Predictions
What the creator concludes. Specific predictions, calls to action, or
forecasts captured verbatim.

## 💡 Key Takeaways
- **Label:** one-sentence takeaway [repeat for 3–5 bullets]
```

If a section has no content (e.g., a 30-second clip with no supporting points), the LLM writes a single sentence like "No additional supporting points presented" to maintain structural consistency.

Existing rules preserved: neutral tone, no meta-phrases ("This video discusses..."), preserve all names/dates/numbers/technical details verbatim.

### 3.2 Code Changes

**File: `app/summarizer/service.py`**

`_summarize_article()` currently hardcodes `"single_summary"`. Change signature:

```python
def _summarize_article(raw_text: str, prompt_name: str = "single_summary") -> tuple[str, int, str]:
```

Replace `prompt_manager.get_prompt("single_summary")` with `prompt_manager.get_prompt(prompt_name)` in all three call sites (short text, single chunk, map step of map-reduce).

In `run_summarization()`, where the call site is:

```python
summary, chunk_count, provider = _summarize_article(raw_text)
```

Change to:

```python
prompt_name = "youtube_summary" if item_source_type == "youtube" else "single_summary"
summary, chunk_count, provider = _summarize_article(raw_text, prompt_name=prompt_name)
```

**File: `app/web/templates/article.html`**

Replace:

```jinja2
{% for paragraph in article.summary_text.split('\n\n') %}
    <p>{{ paragraph }}</p>
{% endfor %}
```

With:

```jinja2
{{ article.summary_text | markdown | safe }}
```

**Migration SQL (one-time, run on deployment):**

Reset YouTube video summaries from the last 3 IST calendar days to `raw` so they regenerate with the new prompt on the next scrape cycle.

```sql
UPDATE articles SET status = 'raw', summary_text = ''
WHERE status = 'summarized'
  AND published_date_ist IN (
    SELECT DISTINCT published_date_ist FROM articles a
    JOIN sources s ON s.id = a.source_id
    WHERE s.source_type = 'youtube'
      AND a.status = 'summarized'
      AND a.published_date_ist >= date('now', '-3 days')
  )
  AND source_id IN (SELECT id FROM sources WHERE source_type = 'youtube');
```

This should be run as part of deployment — either as a numbered migration in `migrations/` or executed directly against the DB.

### 3.3 No other changes

- The daily digest generation (`_generate_youtube_daily_digest`) uses `youtube_digest.md` — untouched.
- The digest template uses `| markdown` already — untouched.
- `single_summary.md` is untouched; RSS article summaries remain as-is.
- `youtube_summary.md` file already exists in `Main Architechture/prompts/` — updated in place.

## 4. Error Handling & Edge Cases

- **Empty/missing section:** The prompt instructs the LLM to output a placeholder line like "No additional supporting points presented" rather than omitting the section header entirely. This ensures consistent visual structure.
- **Short videos (1 paragraph of transcript):** Map-reduce is skipped, `youtube_summary` prompt still applied. The LLM fills in what it can from the limited content — empty sections get placeholder lines.
- **Map-reduce path:** Both the per-chunk summaries and the final reduce synthesis use the same `youtube_summary` prompt name, which is correct — chunks are summarized with `chunk_summary`, and only the final synthesis uses the named prompt.
- **Backward compatibility:** Existing `summary_text` in the DB was generated with the old prompt and has no markdown structure. These will render as a single block of text under `| markdown`, which is no worse than the current plain `split('\n\n')` rendering.
- **RSS articles:** Unaffected — they continue using `single_summary` and the existing plain renderer. (They never enter the per-video summary path in `article.html` because the template is shared; this is fine because RSS summaries are short paragraphs that look acceptable as plain `<p>` blocks.)

## 5. Testing

- **Prompt output validation:** Run the new `youtube_summary.md` against 2–3 sample transcripts. Verify all 4 section headers appear, bullet points render, and no meta-phrases leak through.
- **Template rendering:** Load `article.html` with a mock article containing markdown (headings, bold, bullets). Verify it renders as HTML, not raw markdown.
- **No regressions:** Verify daily YouTube digest still renders correctly. Verify RSS article pages still render correctly.
- **Existing DB data:** View an old article page — confirm it doesn't break, even though the old summary text has no markdown structure.

## 6. Migration: Existing Summaries

Videos already summarized with the old prompt have plain-text `summary_text` in the DB — no markdown structure.

### Auto-migration: Last 3 days

On deployment, reset all YouTube videos from the last 3 days to `status = 'raw'`: all videos with `source_type = 'youtube'`, `status = 'summarized'`, and `published_date_ist` within the last 3 IST calendar days. On the next scrape cycle, the summarizer picks them up with the new `youtube_summary` prompt and regenerates.

### Older videos (4+ days ago)

Left as-is. They render as plain text under the `| markdown` filter — no errors, just less structured. If you later want to regenerate one, update its status manually:

```sql
UPDATE articles SET status = 'raw', summary_text = '' WHERE id = <article_id>;
```

Then trigger a manual run from Settings → Sync Now.

### Newly discovered videos
Automatically get the new prompt — no migration needed.

## 7. Verification

After deploying, confirm the fix with these concrete steps:

1. **Find a newly-summarized YouTube video** (any video summarized after the deployment). Open its article page (`/article/<id>`).
   - You should see 4 sections with headings: 🎯 Main Argument, 📝 Supporting Points, 🔮 Conclusions / Predictions, 💡 Key Takeaways.
   - The "Key Takeaways" section should be a bulleted list with bold labels.
   - Headings should be rendered as `<h2>` elements, not raw `##` text.

2. **Open the YouTube daily digest** (`/youtube`) and expand the "Videos in this digest" footnotes. Click to expand a video that was summarized after the deployment.
   - The footnote detail should show the same 4-section structure.
   - This confirms the `| markdown` filter works in both the article page AND footnote context.

3. **Open an old (pre-deployment) YouTube video** that wasn't regenerated.
   - Confirm the page doesn't error out — the summary renders as plain text.

4. **Open an RSS article page** (`/article/<rss_article_id>`).
   - Confirm it renders the same as before (plain paragraphs, no markdown). RSS wasn't changed.

5. **Open the YouTube daily digest** (`/youtube`).
   - Confirm the digest card text (the synthesized all-channels summary) still renders with its original rich formatting. This wasn't changed.

## 8. Success Criteria

- [ ] Individual YouTube video summary pages show 4 clearly separated sections with headings, bold labels, and bullet points.
- [ ] Per-video footnotes in the YouTube digest card show the improved summary formatting.
- [ ] Daily YouTube digest formatting is unchanged.
- [ ] RSS article summaries are unchanged.
- [ ] Old summaries (pre-migration) still render acceptably without errors.
- [ ] Verification steps 1–5 all pass.
