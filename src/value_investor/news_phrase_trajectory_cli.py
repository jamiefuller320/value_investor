"""CLI for offline news-phrase ↔ trajectory panel (buy / boundary cohort)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.news_phrase_trajectory import (
    LEXICON_FILENAME,
    PANEL_FILENAME,
    REVIEW_MD_FILENAME,
    STATE_FILENAME,
    run_news_phrase_trajectory,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Offline chronological news-phrase panel for the buy∪boundary cohort. "
            "Walk-forward lexicon with rolling watermarks. Observe-only."
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
    parser.add_argument("--train-fraction", type=float, default=0.7)
    parser.add_argument("--min-train-count", type=int, default=4)
    parser.add_argument("--max-phrases", type=int, default=80)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        payload = run_news_phrase_trajectory(
            args.data_dir,
            mode=args.mode,
            train_fraction=args.train_fraction,
            min_train_count=args.min_train_count,
            max_phrases=args.max_phrases,
            tickers=args.tickers,
        )
    except (FileNotFoundError, RuntimeError, ValueError) as err:
        print(str(err), file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(payload["panel"], indent=2))
    else:
        panel = payload["panel"]
        print(f"Wrote {args.data_dir / PANEL_FILENAME}")
        print(f"Wrote {args.data_dir / LEXICON_FILENAME}")
        print(f"Wrote {args.data_dir / STATE_FILENAME}")
        print(f"Wrote {args.data_dir / REVIEW_MD_FILENAME}")
        print(
            f"mode={panel.get('mode')} cohort={panel.get('cohort_ticker_count')} "
            f"news={panel.get('tickers_with_news')} articles={panel.get('article_count')} "
            f"obs={panel.get('observation_count')} promoted={panel.get('promoted_count')} "
            f"watch={panel.get('watch_count')} gen={panel.get('lexicon_generation')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
