# YouTube Individual Video Summary Formatting — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Individual YouTube video summaries get structured 4-section markdown formatting matching the daily digest's readability, and last 3 days of existing summaries regenerate with the new format.

**Architecture:** Small surgical changes across 3 files: rewrite the `youtube_summary.md` prompt to produce fixed-section markdown, add a `prompt_name` parameter to `_summarize_article()` so YouTube articles route to the YouTube-specific prompt, swap `article.html` from plain-text rendering to `| markdown | safe`, and run a one-time SQL migration to reset recent videos. The digest prompt and rendering are untouched.

**Tech Stack:** Python 3.12, Jinja2 templates, SQLite, existing LLM pipeline (`call_llm`)

## Global Constraints

- Daily YouTube digest (`youtube_digest.md`) and its rendering must not change
- RSS article summaries (`single_summary.md`) must not change
- Old summaries (4+ days) must render without errors under the new markdown filter
- Per-video footnotes in the digest card inherit formatting improvements automatically (same `summary_text` field)
- Last 3 IST calendar days of YouTube summaries auto-reset to `raw` on deployment

---

### Task 1: Rewrite YouTube Summary Prompt

**Files:**
- Modify: `Main Architechture/prompts/youtube_summary.md`

**Interfaces:**
- Consumes: nothing (standalone prompt file)
- Produces: prompt template used by `prompt_manager.get_prompt("youtube_summary")` — the LLM reads this and outputs 4-section markdown

- [ ] **Step 1: Replace the prompt file**

Overwrite `Main Architechture/prompts/youtube_summary.md` with the following content:

```markdown
You are a skilled content analyst. Summarize the following YouTube video transcript using the EXACT structure below. Do not deviate from this structure.

CRITICAL: Your summary must retain all specific details — names of people and organizations, exact dates, numbers and statistics, key arguments, and technical details. Do not generalize or omit these.

## 🎯 Main Argument
A concise paragraph capturing the video's core thesis — what the creator is arguing for, explaining, or demonstrating.

## 📝 Supporting Points
The evidence, data, examples, and reasoning the creator uses to build their case. Write as flowing prose (not a bullet list), but cover each distinct point clearly and thoroughly.

## 🔮 Conclusions / Predictions
What the creator concludes. If they made specific predictions, calls to action, or forecasts, capture them verbatim.

## 💡 Key Takeaways
- **Bold label:** one-sentence takeaway
- **Bold label:** one-sentence takeaway
(3–5 bullet points, each with a bold label)

Additional rules:
- If a section has no meaningful content, write a single sentence like "No supporting points were presented" rather than omitting it
- Neutral, objective tone — do not editorialise
- Write in clear, simple English
- Do NOT include phrases like "This video discusses" or "The creator states"
- If the transcript covers multiple unrelated topics, include all of them

TRANSCRIPT:
{text}

SUMMARY:
```

- [ ] **Step 2: Verify the prompt file was written correctly**

```bash
cat "Main Architechture/prompts/youtube_summary.md"
```

Expected: the file contains all 4 section headers (`## 🎯 Main Argument`, `## 📝 Supporting Points`, `## 🔮 Conclusions / Predictions`, `## 💡 Key Takeaways`), the placeholder rule, tone rules, and `{text}` placeholder.

- [ ] **Step 3: Commit**

```bash
git add "Main Architechture/prompts/youtube_summary.md"
git commit -m "feat: rewrite youtube_summary prompt with 4-section fixed structure"
```

---

### Task 2: Route YouTube Articles to `youtube_summary` Prompt

**Files:**
- Modify: `app/summarizer/service.py`

**Interfaces:**
- Consumes: `item_source_type` (already available in `run_summarization()` loop as a string: `"rss"` or `"youtube"`)
- Produces: `_summarize_article(raw_text, prompt_name="single_summary")` — updated signature with default for backward compatibility

- [ ] **Step 1: Change `_summarize_article` signature**

In `app/summarizer/service.py`, line 203, change:

```python
def _summarize_article(raw_text: str) -> tuple[str, int, str]:
```

To:

```python
def _summarize_article(raw_text: str, prompt_name: str = "single_summary") -> tuple[str, int, str]:
```

- [ ] **Step 2: Replace `"single_summary"` with `prompt_name` in the short-text path**

In `_summarize_article`, line 212, change:

```python
summary = call_llm(prompt_manager.get_prompt("single_summary").format(text=raw_text))
```

To:

```python
summary = call_llm(prompt_manager.get_prompt(prompt_name).format(text=raw_text))
```

- [ ] **Step 3: Replace `"single_summary"` with `prompt_name` in the single-chunk path**

In `_summarize_article`, line 221, change:

```python
summary = call_llm(prompt_manager.get_prompt("single_summary").format(text=chunks[0]))
```

To:

```python
summary = call_llm(prompt_manager.get_prompt(prompt_name).format(text=chunks[0]))
```

- [ ] **Step 4: Add `prompt_name` to the call site in `run_summarization`**

In `run_summarization()`, line 114, change:

```python
summary, chunk_count, provider = _summarize_article(raw_text)
```

To:

```python
prompt_name = "youtube_summary" if item_source_type == "youtube" else "single_summary"
summary, chunk_count, provider = _summarize_article(raw_text, prompt_name=prompt_name)
```

- [ ] **Step 5: Verify the code is syntactically correct**

```bash
cd "C:/Users/pc/Documents/My Docs/Projects/personal-website" && python -c "import ast; ast.parse(open('app/summarizer/service.py').read()); print('Syntax OK')"
```

Expected: `Syntax OK`

- [ ] **Step 6: Commit**

```bash
git add app/summarizer/service.py
git commit -m "feat: route youtube articles to youtube_summary prompt"
```

---

### Task 3: Use Markdown Rendering in Article Template

**Files:**
- Modify: `app/web/templates/article.html`

**Interfaces:**
- Consumes: `article.summary_text` (string, may contain markdown from new prompt or plain text from old prompt)
- Produces: same template, but summary renders as HTML via `| markdown | safe` instead of plain `<p>` tags

- [ ] **Step 1: Replace the summary rendering block**

In `app/web/templates/article.html`, lines 35-37, change:

```jinja2
{% if article.summary_text %}
<div class="summary-card">
    <h3>📝 Summary</h3>
    {% for paragraph in article.summary_text.split('\n\n') %}
        <p>{{ paragraph }}</p>
    {% endfor %}
</div>
```

To:

```jinja2
{% if article.summary_text %}
<div class="summary-card">
    <h3>📝 Summary</h3>
    <div class="digest-body">
        {{ article.summary_text | markdown | safe }}
    </div>
</div>
```

Note: The `<div class="digest-body">` wrapper reuses the existing CSS class already used by the daily digest card, ensuring headings, bullet lists, and bold text are styled consistently.

- [ ] **Step 2: Verify the template change**

```bash
cd "C:/Users/pc/Documents/My Docs/Projects/personal-website" && python -c "
from pathlib import Path
t = Path('app/web/templates/article.html').read_text()
assert '| markdown | safe' in t, 'markdown filter not found'
assert 'split(' not in t, 'old split loop still present'
print('Template OK')
"
```

Expected: `Template OK`

- [ ] **Step 3: Commit**

```bash
git add app/web/templates/article.html
git commit -m "feat: render article summaries with markdown filter"
```

---

### Task 4: Migration — Reset Last 3 Days of YouTube Summaries

**Files:**
- Create: `migrations/008_reset_youtube_summaries_last_3_days.sql`

**Interfaces:**
- Consumes: existing `articles` table with `status`, `summary_text`, `published_date_ist`, `source_id` columns
- Produces: YouTube videos from the last 3 IST days set to `status = 'raw'`, `summary_text = ''`

- [ ] **Step 1: Write the migration SQL file**

Create `migrations/008_reset_youtube_summaries_last_3_days.sql`:

```sql
-- Reset YouTube video summaries from the last 3 IST calendar days to 'raw'
-- so they regenerate with the new youtube_summary prompt on the next scrape cycle.

UPDATE articles
SET status = 'raw', summary_text = ''
WHERE status = 'summarized'
  AND published_date_ist IN (
    SELECT DISTINCT a.published_date_ist
    FROM articles a
    JOIN sources s ON s.id = a.source_id
    WHERE s.source_type = 'youtube'
      AND a.status = 'summarized'
      AND a.published_date_ist >= date('now', '-3 days')
  )
  AND source_id IN (SELECT id FROM sources WHERE source_type = 'youtube');
```

- [ ] **Step 2: Verify the migration file exists and is readable**

```bash
wc -l "migrations/008_reset_youtube_summaries_last_3_days.sql"
```

Expected: file exists with ~15 lines

- [ ] **Step 3: Dry-run the migration to count affected rows**

```bash
cd "C:/Users/pc/Documents/My Docs/Projects/personal-website" && python -c "
from app.database import get_db
conn = get_db()
count = conn.execute('''
    SELECT COUNT(*) FROM articles
    WHERE status = 'summarized'
      AND published_date_ist IN (
        SELECT DISTINCT a.published_date_ist
        FROM articles a
        JOIN sources s ON s.id = a.source_id
        WHERE s.source_type = 'youtube'
          AND a.status = 'summarized'
          AND a.published_date_ist >= date('now', '-3 days')
      )
      AND source_id IN (SELECT id FROM sources WHERE source_type = 'youtube')
''').fetchone()[0]
print(f'Would reset {count} YouTube summaries from the last 3 days')
conn.close()
"
```

Expected: prints a count (e.g., `Would reset 12 YouTube summaries from the last 3 days`)

- [ ] **Step 4: Run the migration**

```bash
cd "C:/Users/pc/Documents/My Docs/Projects/personal-website" && python -c "
from app.database import get_db
conn = get_db()
conn.executescript(open('migrations/008_reset_youtube_summaries_last_3_days.sql').read())
conn.commit()
print('Migration applied successfully')
conn.close()
"
```

Expected: `Migration applied successfully`

- [ ] **Step 5: Commit**

```bash
git add migrations/008_reset_youtube_summaries_last_3_days.sql
git commit -m "feat: migration to reset last 3 days of youtube summaries"
```

---

### Task 5: Verification

**Files:**
- No code changes — manual verification against live or local instance

- [ ] **Step 1: Trigger a scrape to regenerate the reset videos**

From the Settings page (`/settings`), click "Sync Now" or run the scheduled scrape. Wait for the summarization to complete (check the settings page status).

- [ ] **Step 2: Verify a newly-summarized YouTube video article page**

Open any YouTube video article that was just re-summarized (from the last 3 days). Confirm:
- The page has a "📝 Summary" heading
- Below it, there are 4 clearly separated sections with `<h2>` headings: 🎯 Main Argument, 📝 Supporting Points, 🔮 Conclusions / Predictions, 💡 Key Takeaways
- The Key Takeaways section shows a bulleted list with bold labels
- No raw `##` or `**` markdown text visible — everything is rendered as HTML

- [ ] **Step 3: Verify per-video footnotes in the digest**

Open `/youtube`, expand the "Videos in this digest" footer. Click to expand a re-summarized video's footnote. Confirm the footnote detail shows the same 4-section structure.

- [ ] **Step 4: Verify old (pre-migration) videos still render**

Open an older YouTube video article (4+ days ago, not regenerated). Confirm:
- The page renders without errors
- The summary text appears (as a single block of text — less structured, but not broken)

- [ ] **Step 5: Verify RSS article pages unchanged**

Open any RSS article page. Confirm it renders the same as before (plain paragraphs, no markdown). The summary card should still use the `<p>` tag format since RSS articles continue using `single_summary.md`.

- [ ] **Step 6: Verify daily YouTube digest unchanged**

Open `/youtube`. Confirm the digest card (the synthesized all-channels text at the top) still renders with its original rich formatting. The `## Today's Highlights`, section headings, and reference tags should all look the same as before.
