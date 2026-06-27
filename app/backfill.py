"""Resumable publication-date and historical-digest backfill."""

import argparse

from app.database import get_db, publication_date_ist
from app.summarizer.service import _generate_daily_digest, _generate_youtube_daily_digest


def backfill_publication_dates() -> int:
    conn = get_db()
    updated = 0
    try:
        rows = conn.execute(
            "SELECT id, published_at FROM articles WHERE published_date_ist IS NULL AND published_at IS NOT NULL"
        ).fetchall()
        for row in rows:
            normalized = publication_date_ist(row["published_at"])
            if normalized:
                conn.execute("UPDATE articles SET published_date_ist=? WHERE id=?", (normalized, row["id"]))
                updated += 1
            if updated and updated % 100 == 0:
                conn.commit()
        conn.execute(
            """INSERT INTO backfill_state(operation,status) VALUES ('publication_dates','completed')
               ON CONFLICT(operation) DO UPDATE SET status='completed', updated_at=CURRENT_TIMESTAMP,
               error_message=NULL"""
        )
        conn.commit()
        return updated
    finally:
        conn.close()


def regenerate_history() -> int:
    conn = get_db()
    completed = 0
    try:
        for media_type, generator in (("rss", _generate_daily_digest), ("youtube", _generate_youtube_daily_digest)):
            dates = conn.execute(
                """SELECT DISTINCT a.published_date_ist AS d FROM articles a
                   JOIN sources s ON s.id=a.source_id WHERE a.status='summarized'
                   AND a.published_date_ist IS NOT NULL AND s.source_type=? ORDER BY d""",
                (media_type,),
            ).fetchall()
            for row in dates:
                operation = f"digest:{media_type}:{row['d']}"
                if conn.execute("SELECT 1 FROM backfill_state WHERE operation=? AND status='completed'", (operation,)).fetchone():
                    continue
                try:
                    generator(conn, row["d"])
                    conn.execute(
                        """INSERT INTO backfill_state(operation,status) VALUES (?, 'completed')
                           ON CONFLICT(operation) DO UPDATE SET status='completed', updated_at=CURRENT_TIMESTAMP, error_message=NULL""",
                        (operation,),
                    )
                    conn.commit(); completed += 1
                except Exception as exc:
                    conn.rollback()
                    conn.execute(
                        """INSERT INTO backfill_state(operation,status,error_message) VALUES (?, 'failed', ?)
                           ON CONFLICT(operation) DO UPDATE SET status='failed', updated_at=CURRENT_TIMESTAMP, error_message=excluded.error_message""",
                        (operation, str(exc)[:500]),
                    )
                    conn.commit()
        return completed
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--regenerate-digests", action="store_true")
    args = parser.parse_args()
    print(f"Publication dates updated: {backfill_publication_dates()}")
    if args.regenerate_digests:
        print(f"Historical digests regenerated: {regenerate_history()}")


if __name__ == "__main__":
    main()
