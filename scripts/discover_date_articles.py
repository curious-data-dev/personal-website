"""Step 1: scrape all RSS feeds, then report which articles are attributable
to a given date (published_date_ist). Does NOT generate any digest or call the
LLM — pure discovery for confirmation before digest generation."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.scraper.service import run_scrape
from app.database import get_db
from app.summarizer.service import run_summarization


def discover(date_str: str) -> list[dict]:
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT a.id, a.title, a.status, a.published_at, a.fetched_at,
                      length(a.raw_text) raw_len,
                      s.name source, s.source_type
               FROM articles a JOIN sources s ON s.id=a.source_id
               WHERE a.published_date_ist=?
               ORDER BY a.published_at""",
            (date_str,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="2026-07-31")
    parser.add_argument("--skip-scrape", action="store_true")
    args = parser.parse_args()

    if not args.skip_scrape:
        print("Scraping all RSS feeds...")
        stats = run_scrape(on_progress=lambda m: print("  ", m))
        print(f"Scrape done: {stats}")
    else:
        print("Skipping scrape (existing DB state).")

    print(f"\n=== Articles attributable to {args.date} (published_date_ist) ===")
    arts = discover(args.date)
    for a in arts:
        print(f"  #{a['id']} [{a['source_type']}] {a['source']} | {a['title']}")
        print(f"        status={a['status']} raw_len={a['raw_len']} published={a['published_at']} fetched={a['fetched_at']}")
    print(f"\nTotal attributable: {len(arts)}")

    # Note which of these would need summarization (not yet summarized)
    to_summarize = [a for a in arts if a["status"] != "summarized"]
    print(f"To be summarized (status != summarized): {len(to_summarize)}")
    for a in to_summarize:
        print(f"  -> #{a['id']} {a['title'][:70]}")


if __name__ == "__main__":
    main()
