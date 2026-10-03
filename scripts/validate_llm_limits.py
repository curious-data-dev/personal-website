"""Validate LLM pacing: run real digest generation and report provider usage.

Works on a COPY of data/aggregator.db by default, so production data is not
touched (pass --in-place to mutate the real DB).

Modes:
    (default)      Gemini + DeepSeek available → measures the fallback rate
    --no-deepseek  Gemini only → proves the pipeline completes without any paid
                   DeepSeek calls; any failure here is a hard FAIL.

Examples:
    python scripts/validate_llm_limits.py --date 2026-10-01 --type rss
    python scripts/validate_llm_limits.py --date 2026-10-01 --no-deepseek
"""

import argparse
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.database as database
from app.config import settings


def _snapshot(src: Path, dst: Path) -> None:
    source = sqlite3.connect(str(src))
    target = sqlite3.connect(str(dst))
    try:
        source.backup(target)  # consistent copy, includes WAL
    finally:
        target.close()
        source.close()


def _print_breakdown(rows: list[dict]) -> dict:
    gemini_ok = deepseek_ok = fallbacks = 0
    print("  provider   event                    count   in_tok   out_tok   waited_s")
    for r in rows:
        print(
            f"  {r['provider']:<10} {r['event']:<22} {r['n']:>5} "
            f"{r['tin']:>8} {r['tout']:>9} {r['waited']:>10.1f}"
        )
        if r["event"] == "success" and r["provider"] == "gemini":
            gemini_ok += r["n"]
        elif r["event"] == "success" and r["provider"] == "deepseek":
            deepseek_ok += r["n"]
        elif r["event"] == "fallback":
            fallbacks += r["n"]
    total_ok = gemini_ok + deepseek_ok
    rate = (deepseek_ok / total_ok * 100) if total_ok else 0.0
    print(
        f"\n  successful calls: gemini={gemini_ok} deepseek={deepseek_ok} "
        f"(fallback rate {rate:.1f}%) | explicit fallback events={fallbacks}"
    )
    return {"gemini_ok": gemini_ok, "deepseek_ok": deepseek_ok, "fallback_rate": rate}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--type", choices=["rss", "youtube", "both"], default="both")
    parser.add_argument("--no-deepseek", action="store_true", help="disable the paid fallback")
    parser.add_argument("--in-place", action="store_true", help="mutate the real DB")
    args = parser.parse_args()

    src = Path(database.DB_PATH)
    if args.in_place:
        work = src
        print(f"Using REAL DB: {src}")
    else:
        work_dir = Path(tempfile.mkdtemp(prefix="llm-validate-"))
        work = work_dir / "aggregator.db"
        _snapshot(src, work)
        database.DB_PATH = work
        print(f"Using DB copy: {work}")

    database.init_db()

    if args.no_deepseek:
        settings.deepseek_api_key = ""
        print("DeepSeek DISABLED — Gemini-only run\n")
    else:
        print("DeepSeek enabled\n")

    from app.summarizer.llm import get_llm_usage_breakdown
    from app.summarizer.service import _generate_daily_digest, _generate_youtube_daily_digest

    started = time.time()
    error: str | None = None
    conn = database.get_db()
    try:
        try:
            if args.type in ("rss", "both"):
                _generate_daily_digest(conn, args.date)
                conn.commit()
            if args.type in ("youtube", "both"):
                _generate_youtube_daily_digest(conn, args.date)
                conn.commit()
        except Exception as exc:  # noqa: BLE001 - report, don't crash the harness
            error = f"{type(exc).__name__}: {exc}"
    finally:
        conn.close()
    elapsed = time.time() - started

    print(f"\nDigest generation for {args.date} ({args.type}) — {elapsed:.1f}s")
    if error:
        print(f"  ERROR: {error}")
    stats = _print_breakdown(get_llm_usage_breakdown(since=started))

    if args.no_deepseek:
        ok = error is None and stats["deepseek_ok"] == 0
        print(f"\nRESULT: {'PASS' if ok else 'FAIL'} (Gemini-only completion)")
        return 0 if ok else 1

    ok = stats["deepseek_ok"] == 0
    print(f"\nRESULT: {'PASS' if ok else 'REVIEW'} (DeepSeek calls = {stats['deepseek_ok']})")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
