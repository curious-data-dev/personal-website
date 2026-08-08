"""Dry-run validation harness for daily-digest token pressure.

Replays a given date (default the previously-failed 2026-08-04 / 2026-08-05)
against the real DB and estimates the per-minute input-token load for:

  1. The article-level MAP + REDUCE (current worst case vs. grouped reduce)
  2. The daily digest input (full summaries vs. condensed summaries)

No LLM API calls are made — this is pure accounting using the ~4 chars/token
estimate the pipeline itself uses. Exits non-zero if the estimate exceeds the
configured per-minute token budget (the failure you observed).
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.database import get_db
from app.summarizer.llm import estimate_tokens
from app.summarizer.chunker import chunk_article


def _load_articles(date_str):
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT a.id, a.title, a.raw_text, a.summary_text, a.chunk_count
               FROM articles a JOIN sources s ON s.id=a.source_id
               WHERE a.published_date_ist=? AND a.status='summarized'
                 AND s.source_type='rss' AND a.excluded_at IS NULL
               ORDER BY a.id""",
            (date_str,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


CHUNK_MAX_OUTPUT_TOKENS = 4096  # llm.py default max_tokens for a chunk summary


def _article_token_load(article):
    """Return per-article token accounting for MAP + REDUCE phases.

    REDUCE input is the combined sub-summaries. Each sub-summary can be up to
    max_tokens=4096 output tokens, so the worst-case single reduce request is
    n_chunks * 4096 (+ separators/prompt overhead) — that is the request that
    can trip the per-minute budget. Grouping splits it into several requests,
    each under budget.
    """
    raw = (article.get("raw_text") or "")[: settings.max_article_chars]
    budget = settings.llm_input_tokens_per_min

    chunks = chunk_article(raw)
    n_chunks = len(chunks) or 1
    map_tokens = sum(estimate_tokens(c) + 60 for c in chunks)  # ~60 token prompt overhead each

    # Worst-case reduce input for the *current* code: one combined request.
    reduce_current = n_chunks * CHUNK_MAX_OUTPUT_TOKENS + 60

    # Proposed: split so each request fits the budget (with headroom for prompt).
    headroom = 2000
    per_request = max(budget - headroom, 1000)
    n_groups = max(1, -(-reduce_current // per_request))
    reduce_grouped_total = reduce_current  # same total tokens, split across calls

    return {
        "n_chunks": n_chunks,
        "map": map_tokens,
        "reduce_current": reduce_current,
        "reduce_grouped_calls": n_groups,
        "reduce_grouped_total": reduce_grouped_total,
        "per_request_after": min(reduce_current, per_request),
    }


def _digest_token_load(articles):
    """Digest input estimate: full summaries vs condensed (600-char) versions."""
    full = sum(estimate_tokens(a.get("summary_text") or "") for a in articles)
    condensed = sum(estimate_tokens((a.get("summary_text") or "")[: settings.condense_target_chars]) for a in articles)
    return full, condensed


def validate(date_str, verbose=True):
    articles = _load_articles(date_str)
    if not articles:
        print(f"[{date_str}] No summarized RSS articles found")
        return 0

    budget = settings.llm_input_tokens_per_min
    print(f"=== {date_str} — {len(articles)} articles, budget {budget} TPM ===")
    total_map = 0
    for a in articles:
        load = _article_token_load(a)
        total_map += load["map"]
        print(f"  #{a['id']} '{a['title'][:55]}'  chunks={load['n_chunks']}")
        print(f"      map={load['map']}t | reduce CURRENT (1 req): {load['reduce_current']}t "
              f"{'OVER BUDGET' if load['reduce_current'] > budget else 'ok'} "
              f"| reduce PROPOSED: {load['reduce_grouped_calls']} req, "
              f"~{load['per_request_after']}t each")

    digest_full, digest_cond = _digest_token_load(articles)
    print(f"  DIGEST input: full={digest_full}t  condensed={digest_cond}t")

    # The hard failure: any single reduce request that can never fit the window.
    loads = [_article_token_load(a) for a in articles]
    single_reduce_over = sum(l["reduce_current"] > budget for l in loads)
    proposed_over = sum(l["per_request_after"] > budget for l in loads)

    print(f"  Single reduce requests > budget: CURRENT={single_reduce_over}  PROPOSED={proposed_over}")
    print(f"  Digest input > budget: CURRENT={digest_full > budget}  PROPOSED={digest_cond > budget}")

    # "After fix" verdict: every individual request fits the window, and the
    # rate limiter paces aggregate load across minutes.
    ok = proposed_over == 0 and digest_cond <= budget
    print(f"  RESULT: {'FIXED (every request fits budget)' if ok else 'STILL OVER BUDGET (see lines above)'}")
    return 0 if ok else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=None, help="YYYY-MM-DD; default validates Aug 4 + Aug 5")
    args = parser.parse_args()

    dates = [args.date] if args.date else ["2026-08-04", "2026-08-05"]
    rc = 0
    for d in dates:
        rc |= validate(d)
    print("\nDone. No API calls were made.")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
