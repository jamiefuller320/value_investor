"""CLI to append and render parked / later ideas."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.deferred_ideas import (
    DEFAULT_MARKDOWN,
    DEFAULT_STORE,
    add_idea,
    load_store,
    set_idea_status,
    write_markdown,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Manage parked/later ideas for periodic review (docs/deferred-ideas.json)"
    )
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    sub = parser.add_subparsers(dest="command", required=True)

    add_p = sub.add_parser("add", help="Append a parked idea and refresh markdown")
    add_p.add_argument("--title", required=True)
    add_p.add_argument("--summary", required=True)
    add_p.add_argument(
        "--category",
        choices=["not_now", "later", "security", "both"],
        default="later",
    )
    add_p.add_argument("--revisit-when", default="")
    add_p.add_argument("--section", default=None, help="learning|universe|research|ops|not_now|security")
    add_p.add_argument("--tags", default="", help="Comma-separated tags")
    add_p.add_argument("--source", default="", help="Agent URL or bc-id")
    add_p.add_argument("--allow-duplicate", action="store_true")
    add_p.add_argument("--json", action="store_true")

    sub.add_parser("render", help="Regenerate docs/deferred-review.md from JSON")

    list_p = sub.add_parser("list", help="List open ideas")
    list_p.add_argument("--category", choices=["not_now", "later", "security", "both", "all"], default="all")
    list_p.add_argument("--json", action="store_true")

    status_p = sub.add_parser("status", help="Set idea status (open|done|drop|now)")
    status_p.add_argument("idea_id")
    status_p.add_argument("status", choices=["open", "done", "drop", "now"])

    args = parser.parse_args(argv)

    if args.command == "add":
        tags = [t.strip() for t in args.tags.split(",") if t.strip()]
        idea, created = add_idea(
            title=args.title,
            summary=args.summary,
            category=args.category,
            revisit_when=args.revisit_when,
            tags=tags,
            section=args.section,
            source=args.source,
            store_path=args.store,
            allow_duplicate=args.allow_duplicate,
        )
        write_markdown(store_path=args.store, markdown_path=args.markdown)
        if args.json:
            print(json.dumps({"created": created, "idea": idea}, indent=2))
        else:
            verb = "Added" if created else "Already present"
            print(f"{verb} {idea['id']}: {idea['title']}")
            print(f"Updated {args.markdown}")
        return 0

    if args.command == "render":
        path = write_markdown(store_path=args.store, markdown_path=args.markdown)
        print(f"Wrote {path}")
        return 0

    if args.command == "list":
        store = load_store(args.store)
        ideas = [i for i in store.get("ideas") or [] if i.get("status", "open") == "open"]
        if args.category != "all":
            if args.category == "both":
                ideas = [i for i in ideas if i.get("category") in {"later", "both"}]
            else:
                ideas = [i for i in ideas if i.get("category") == args.category]
        if args.json:
            print(json.dumps(ideas, indent=2))
        else:
            for idea in ideas:
                print(f"{idea.get('id')}\t{idea.get('category')}\t{idea.get('title')}")
        return 0

    if args.command == "status":
        idea = set_idea_status(args.idea_id, args.status, store_path=args.store)
        write_markdown(store_path=args.store, markdown_path=args.markdown)
        print(f"Set {idea['id']} -> {idea['status']}")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
