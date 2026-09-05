"""CLI for the observe-only material-event news journal."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.news_event_journal import (
    JOURNAL_FILENAME,
    REVIEW_MD_FILENAME,
    RULES_FILENAME,
    STATE_FILENAME,
    run_news_event_journal,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Observe-only material-event journal for the buy∪boundary cohort. "
            "Classifies existing news_manifest headlines and joins later filings."
        )
    )
    parser.add_argument("--data-dir", type=Path, default=Path("docs/data"))
    parser.add_argument(
        "--mode",
        choices=("full", "rolling"),
        default="full",
        help="full rebuild (default) or rolling watermark refresh",
    )
    parser.add_argument(
        "--tickers",
        nargs="*",
        default=None,
        help="Optional ticker subset (otherwise buy∪boundary cohort)",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        payload = run_news_event_journal(
            args.data_dir,
            mode=args.mode,
            tickers=args.tickers,
        )
    except (FileNotFoundError, RuntimeError, ValueError) as err:
        print(str(err), file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(payload["journal"], indent=2))
    else:
        journal = payload["journal"]
        print(f"Wrote {args.data_dir / JOURNAL_FILENAME}")
        print(f"Wrote {args.data_dir / RULES_FILENAME}")
        print(f"Wrote {args.data_dir / STATE_FILENAME}")
        print(f"Wrote {args.data_dir / REVIEW_MD_FILENAME}")
        print(
            f"mode={journal.get('mode')} cohort={journal.get('cohort_ticker_count')} "
            f"news={journal.get('tickers_with_news')} articles={journal.get('article_count')} "
            f"events={journal.get('event_count')} confirmed={journal.get('confirmed_count')} "
            f"issuer_reject={journal.get('issuer_reject_count')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
