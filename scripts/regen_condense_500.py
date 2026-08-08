"""Regenerate condensed summaries (500-word target) for a date's articles,
then regenerate the digest. Live LLM calls.

Clears the cached condensed_summary on the articles so _get_condensed_summary
re-runs condensation with the new condense_summary.md / condense_target_chars.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import get_db
from app.summarizer.service import _generate_daily_digest, _generate_youtube_daily_digest


def main() -> None:
    conn = get_db()
    try:
        for date_str in ["2026-08-04", "2026-07-31"]:
            rows = conn.execute(
                """SELECT a.id FROM articles a
                   JOIN digest_articles da ON da.article_id = a.id
                   JOIN daily_digests dg ON dg.id = da.digest_id
                   WHERE dg.date = ?""",
                (date_str,),
            ).fetchall()
            yt_rows = conn.execute(
                """SELECT a.id FROM articles a
                   JOIN youtube_digest_videos dv ON dv.article_id = a.id
                   JOIN youtube_digests yd ON yd.id = dv.digest_id
                   WHERE yd.date = ?""",
                (date_str,),
            ).fetchall()
            for row in list(rows) + list(yt_rows):
                conn.execute(
                    "UPDATE articles SET condensed_summary = NULL WHERE id = ?",
                    (row["id"],),
                )
            conn.commit()
            print(f"Cleared {len(rows) + len(yt_rows)} cached condensations for {date_str}")

        _generate_daily_digest(conn, "2026-08-04", on_progress=lambda m: print("  ", m))
        conn.commit()
        print("Aug 4 RSS digest regenerated.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
