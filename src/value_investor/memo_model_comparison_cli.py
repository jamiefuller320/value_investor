"""CLI for the observe-only memo model comparison.

``select`` freezes the names; ``generate`` writes the memos (workflow
``memo-model-comparison.yml``); ``decide`` applies the pre-declared rule once
the owner's blind ratings are in. ops-monitor reads the store daily
(``check_memo_model_comparison``). See docs/ops/memo-model-comparison.md.
"""

from __future__ import annotations

import argparse
from datetime import UTC, date, datetime
from pathlib import Path

from value_investor.memo_model_comparison import (
    decide,
    due_for_generation,
    findings,
    json_dumps,
    load_json,
    ratings_progress,
    run_generation,
    select_names,
    store_dir,
)
from value_investor.storage import write_json


def _now(raw: str | None) -> datetime:
    if not raw:
        return datetime.now(UTC)
    moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Memo model comparison (observe-only)")
    parser.add_argument("--repo-root", type=Path, default=Path())
    parser.add_argument("--now", help="Override the run timestamp (ISO-8601)")
    sub = parser.add_subparsers(dest="command", required=True)

    sel = sub.add_parser("select", help="Apply the selection rule and freeze manifest.json")
    sel.add_argument("--before", help="Selection date YYYY-MM-DD (default today, UTC)")
    sel.add_argument(
        "--apply", action="store_true", help="Write manifest.json (refuses to overwrite)"
    )

    gen = sub.add_parser("generate", help="Generate missing memos for both models")
    gen.add_argument("--apply", action="store_true", help="Call the models and write the store")
    gen.add_argument(
        "--if-due", action="store_true", help="Exit 0 without work when nothing is due"
    )

    dec = sub.add_parser("decide", help="Apply the decision rule to complete owner ratings")
    dec.add_argument("--apply", action="store_true", help="Write decision.json")

    sub.add_parser("status", help="Print the ops findings for the store")

    args = parser.parse_args(argv)
    root = args.repo_root
    now = _now(args.now)
    store = store_dir(root)

    if args.command == "select":
        before = date.fromisoformat(args.before) if args.before else now.date()
        manifest = select_names(root, before=before, now=now)
        if args.apply:
            path = store / "manifest.json"
            if path.is_file():
                print(
                    f"{path} exists; the selection is frozen. Delete it deliberately to reselect."
                )
                return 1
            write_json(path, manifest, compact=False)
        print(json_dumps(manifest))
        return 0

    if args.command == "generate":
        if args.if_due and not due_for_generation(root):
            print("Nothing due: comparison ready, capped, or not selected.")
            return 0
        manifest = load_json(store / "manifest.json")
        if manifest is None:
            print("manifest.json missing; run select --apply first")
            return 1
        if not args.apply:
            print(json_dumps({"names": len(manifest["names"]), "budget": manifest["budget"]}))
            return 0
        from value_investor.cursor_api_key import resolve_cursor_api_key

        key, _env = resolve_cursor_api_key()
        status = run_generation(root, now=now, api_key=key)
        view = {
            k: status.get(k)
            for k in ("state", "complete_pairs", "spend", "errors", "runtime_models")
        }
        print(json_dumps(view))
        return 1 if status.get("errors") and status.get("state") != "ready_for_review" else 0

    if args.command == "decide":
        manifest = load_json(store / "manifest.json")
        results = load_json(store / "results.json")
        ratings = load_json(store / "ratings.json")
        key = load_json(store / "blind_key.json")
        if not (manifest and results and ratings and key):
            print("Need manifest.json, results.json, ratings.json and blind_key.json")
            return 1
        done, total = ratings_progress(ratings)
        if not total or done < total:
            print(f"Ratings incomplete: {done}/{total}")
            return 1
        verdict = decide(manifest, results, ratings, key)
        verdict["generated_at"] = now.isoformat()
        if args.apply:
            write_json(store / "decision.json", verdict, compact=False)
        print(json_dumps(verdict))
        return 0

    print(json_dumps(findings(root, now)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
