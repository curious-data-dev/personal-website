"""Step 2: generate the digest for a date's confirmed article set (live LLM).

Regenerates both the RSS daily digest and the YouTube daily digest for the
given date, using the already-summarized articles attributable to it."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import get_db
from app.summarizer.service import _generate_daily_digest, _generate_youtube_daily_digest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="2026-07-31")
    parser.add_argument("--skip-youtube", action="store_true")
    args = parser.parse_args()

    conn = get_db()
    try:
        rss_articles = conn.execute(
            """SELECT COUNT(*) n FROM articles a JOIN sources s ON s.id=a.source_id
               WHERE a.published_date_ist=? AND a.status='summarized'
                 AND s.source_type='rss' AND a.excluded_at IS NULL""",
            (args.date,),
        ).fetchone()["n"]
        yt_articles = conn.execute(
            """SELECT COUNT(*) n FROM articles a JOIN sources s ON s.id=a.source_id
               WHERE a.published_date_ist=? AND a.status='summarized'
                 AND s.source_type='youtube' AND a.excluded_at IS NULL""",
            (args.date,),
        ).fetchone()["n"]
        print(f"RSS articles for {args.date}: {rss_articles} | YouTube: {yt_articles}")

        if rss_articles:
            print("Generating RSS digest...")
            _generate_daily_digest(conn, args.date, on_progress=lambda m: print("  ", m))
            conn.commit()
            print("RSS digest done.")

        if yt_articles and not args.skip_youtube:
            print("Generating YouTube digest...")
            _generate_youtube_daily_digest(conn, args.date, on_progress=lambda m: print("  ", m))
            conn.commit()
            print("YouTube digest done.")

        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
