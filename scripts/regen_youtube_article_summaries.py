"""Regenerate per-video article-level summaries (articles.summary_text) for YouTube.

Rewrites each video's stored summary — the text shown in the collapsible
per-video footnotes on the YouTube digest page and on the video's article
page — as a detailed story write-up (bold headline + flowing prose) using
the youtube_digest_story_extract prompt. Uses only data already in the DB
(no transcript fetching) and does NOT touch the daily digest text.

Usage:
  python scripts/regen_youtube_article_summaries.py --since 2026-08-11
  python scripts/regen_youtube_article_summaries.py --date 2026-08-14
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.database import get_db, update_article_summary
from app.summarizer.llm import call_llm, get_last_provider
from app.summarizer.service import _get_digest_extract_prompt


def safe_print(msg: str) -> None:
    """Print without crashing on non-cp1252 characters (emoji in titles etc.)."""
    try:
        print("  ", msg)
    except UnicodeEncodeError:
        print("  ", msg.encode("ascii", "backslashreplace").decode("ascii"))


def _strip_ref_tags(text: str, ref_num: int) -> str:
    """Remove the [n] / [REF n] tags the extract prompt appends per block."""
    pat = re.compile(r"\s*\[(?:REF\s+)?%d\]\s*$" % ref_num)
    blocks = [pat.sub("", b) for b in re.split(r"\n\s*\n", text)]
    return "\n\n".join(b.strip() for b in blocks if b.strip())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--since", default="2026-08-11",
        help="Regenerate videos with published_date_ist >= this date (default 2026-08-11)",
    )
    parser.add_argument(
        "--date", default=None,
        help="Regenerate only this exact date (overrides --since)",
    )
    args = parser.parse_args()

    conn = get_db()
    try:
        if args.date:
            date_cond, date_params = "a.published_date_ist = ?", (args.date,)
        else:
            date_cond, date_params = "a.published_date_ist >= ?", (args.since,)
        rows = conn.execute(
            f"""SELECT a.id, a.title, a.published_date_ist, a.summary_text
                FROM articles a JOIN sources s ON s.id = a.source_id
                WHERE s.source_type = 'youtube' AND a.status = 'summarized'
                  AND a.excluded_at IS NULL AND {date_cond}
                ORDER BY a.published_date_ist""",
            date_params,
        ).fetchall()
        print(f"Found {len(rows)} YouTube video(s) to regenerate")

        done = 0
        for i, r in enumerate(rows, start=1):
            safe_print(f"[{i}/{len(rows)}] #{r['id']} {r['published_date_ist']} {r['title'][:60]}")
            summary = r["summary_text"] or ""
            if not summary.strip():
                safe_print("  (empty summary_text, skipping)")
                continue
            prompt = _get_digest_extract_prompt(is_youtube=True).format(
                ref_num=1,
                summary=summary,
            )
            try:
                out = call_llm(
                    prompt,
                    model=settings.gemini_digest_model,
                    max_tokens=8192,
                    on_progress=safe_print,
                )
            except Exception as e:
                safe_print(f"  FAILED: {e}")
                continue
            cleaned = _strip_ref_tags(out, 1)
            if not cleaned.strip():
                safe_print("  (empty output, keeping existing summary)")
                continue
            update_article_summary(
                conn, r["id"], cleaned,
                chunk_count=0, llm_provider=get_last_provider() or "gemini",
            )
            conn.commit()
            done += 1
            safe_print(f"  -> stored {len(cleaned)} chars")
        print(f"Done. Regenerated {done}/{len(rows)} summaries.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
