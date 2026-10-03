"""Export digest(s) to HTML + EPUB and email them to Kindle.

Without arguments this behaves like the daily job's Kindle phase: yesterday's
RSS + YouTube digests, plus any older digest that was recently regenerated
(never today's).

With --date it targets one specific date (both types by default). This is the
main testing entry point:

    python scripts/send_kindle_digests.py --date 2026-10-02 --dry-run
    python scripts/send_kindle_digests.py --date 2026-10-02 --type rss
    python scripts/send_kindle_digests.py --date 2026-10-02 --force

Flags:
    --dry-run    build the HTML/EPUB files but do not send or record
    --force      send even if the content hash matches the last send
    --refreshed  add the " (Updated <today>)" suffix (older-digest naming)
    --recipient  override the configured Kindle address
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import get_db
from app.kindle.service import export_and_send_digest, send_digests_to_kindle


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="specific digest date (YYYY-MM-DD)")
    parser.add_argument("--type", choices=["rss", "youtube", "both"], default="both")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--refreshed", action="store_true")
    parser.add_argument("--recipient", default=None)
    args = parser.parse_args()

    if args.date:
        types = ["rss", "youtube"] if args.type == "both" else [args.type]
        conn = get_db()
        try:
            for digest_type in types:
                result = export_and_send_digest(
                    conn,
                    digest_type,
                    args.date,
                    refreshed=args.refreshed,
                    force=args.force,
                    dry_run=args.dry_run,
                    recipient=args.recipient,
                )
                print(result)
        finally:
            conn.close()
        return

    summary = send_digests_to_kindle(
        regenerated=None,
        force=args.force,
        dry_run=args.dry_run,
        recipient=args.recipient,
    )
    for result in summary.get("results", []):
        print(result)
    print(
        f"\n{'[dry-run] ' if args.dry_run else ''}"
        f"enabled={summary.get('enabled')} today={summary.get('today')} "
        f"yesterday={summary.get('yesterday')}"
        f"{' reason=' + summary['reason'] if summary.get('reason') else ''}"
    )


if __name__ == "__main__":
    main()
