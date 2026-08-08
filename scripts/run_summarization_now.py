"""Summarize all raw articles, regenerating digests for affected dates.

Live LLM calls. This picks up the newly-scraped articles (incl. the Aug 4
Hindu Evening Wrap #590) and, via stale-detection within the 7-day window,
regenerates the Aug 4 RSS digest so the Hindu article appears."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.summarizer.service import run_summarization


def main() -> None:
    stats = run_summarization(on_progress=lambda m: print(m))
    print("STATS:", stats)


if __name__ == "__main__":
    main()
