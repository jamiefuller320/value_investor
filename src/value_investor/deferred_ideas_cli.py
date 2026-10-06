"""CLI to append and render parked / later ideas."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.deferred_ideas import (
    DEFAULT_MARKDOWN,
    DEFAULT_STORE,
    add_fragment,
    add_idea,
    list_open_fragments,
    load_store,
    set_fragment_status,
    set_idea_status,
    set_idea_trigger,
    write_markdown,
)


def _parse_trigger(raw: str) -> dict | None:
    if not raw.strip():
        return None
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise SystemExit(f"--trigger must be JSON: {exc}") from exc


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
    add_p.add_argument(
        "--section", default=None, help="learning|universe|research|ops|not_now|security"
    )
    add_p.add_argument("--tags", default="", help="Comma-separated tags")
    add_p.add_argument("--source", default="", help="Agent URL or bc-id")
    add_p.add_argument("--allow-duplicate", action="store_true")
    add_p.add_argument(
        "--trigger",
        default="",
        help='Machine-checkable trigger JSON, e.g. \'{"all":[{"on_or_after":"2026-12-01"}]}\'',
    )
    add_p.add_argument("--json", action="store_true")

    sub.add_parser("render", help="Regenerate docs/deferred-review.md from JSON")

    list_p = sub.add_parser("list", help="List open ideas")
    list_p.add_argument(
        "--category", choices=["not_now", "later", "security", "both", "all"], default="all"
    )
    list_p.add_argument("--json", action="store_true")
    list_p.add_argument(
        "--fragments",
        action="store_true",
        help="List open fragments instead of deferred ideas",
    )

    status_p = sub.add_parser("status", help="Set idea status (open|done|drop|now)")
    status_p.add_argument("idea_id")
    status_p.add_argument("status", choices=["open", "done", "drop", "now"])
    status_p.add_argument("--note", default="", help="Why (stored as status_note)")

    trig_p = sub.add_parser(
        "set-trigger", help="Attach a machine-checkable trigger (docs/ops/deferred-triggers.md)"
    )
    trig_p.add_argument("idea_id")
    trig_group = trig_p.add_mutually_exclusive_group(required=True)
    trig_group.add_argument("--trigger", help="Trigger JSON ({'all'|'any': [conditions]})")
    trig_group.add_argument("--clear", action="store_true")
    trig_p.add_argument("--revisit-when", default=None, help="Also replace the free-text trigger")

    triggers_p = sub.add_parser(
        "triggers", help="Evaluate structured triggers and frozen-book mentions (read-only)"
    )
    triggers_p.add_argument("--json", action="store_true")

    fragment_p = sub.add_parser("fragment", help="Append a scratch-pad thought fragment")
    fragment_p.add_argument("--text", required=True)
    fragment_p.add_argument("--tags", default="", help="Comma-separated tags")
    fragment_p.add_argument("--source", default="")
    fragment_p.add_argument("--allow-duplicate", action="store_true")
    fragment_p.add_argument("--json", action="store_true")

    frag_status_p = sub.add_parser(
        "fragment-status",
        help="Set fragment status (open|done|drop|now) — done = promoted/resolved",
    )
    frag_status_p.add_argument("fragment_id")
    frag_status_p.add_argument("status", choices=["open", "done", "drop", "now"])

    rebase_p = sub.add_parser(
        "rebase-ids",
        help=(
            "After `git merge <base>`: keep base IDs, renumber this branch's colliding "
            "new entries and rewrite their references in lines the branch added"
        ),
    )
    rebase_p.add_argument("--base", default="origin/main")
    rebase_p.add_argument("--apply", action="store_true", help="Write store, markdown, refs")
    rebase_p.add_argument("--json", action="store_true")

    check_p = sub.add_parser(
        "check-ids", help="Fail on duplicate IDs or base IDs whose title changed (CI guard)"
    )
    check_p.add_argument("--base", default=None, help="Git ref to compare base IDs against")

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
            trigger=_parse_trigger(args.trigger),
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
        if args.fragments:
            fragments = list_open_fragments(store_path=args.store)
            if args.json:
                print(json.dumps(fragments, indent=2))
            else:
                for row in fragments:
                    print(f"{row.get('id')}\t{row.get('text')}")
            return 0
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
        idea = set_idea_status(args.idea_id, args.status, note=args.note, store_path=args.store)
        write_markdown(store_path=args.store, markdown_path=args.markdown)
        print(f"Set {idea['id']} -> {idea['status']}")
        return 0

    if args.command == "set-trigger":
        trigger = None if args.clear else _parse_trigger(args.trigger)
        idea = set_idea_trigger(
            args.idea_id, trigger, revisit_when=args.revisit_when, store_path=args.store
        )
        write_markdown(store_path=args.store, markdown_path=args.markdown)
        print(f"{'Cleared' if trigger is None else 'Set'} trigger on {idea['id']}")
        return 0

    if args.command == "triggers":
        from value_investor.deferred_triggers import check_deferred_triggers

        payload = check_deferred_triggers(load_store(args.store))
        if args.json:
            print(json.dumps(payload, indent=2, default=str))
            return 0
        print(f"{payload['with_trigger']} of {payload['open_ideas']} open ideas machine-checked")
        for row in payload["met"]:
            print(f"MET      {row['id']}\t{row['title']}")
        for row in payload["unknown"]:
            print(f"UNKNOWN  {row['id']}\t{'; '.join(row['reasons'])}")
        for row in payload["frozen_mentions"]:
            print(f"FROZEN   {row['id']}\tnames {', '.join(row['tracks'])}")
        return 0

    if args.command == "fragment":
        tags = [t.strip() for t in args.tags.split(",") if t.strip()]
        fragment, created = add_fragment(
            args.text,
            tags=tags,
            source=args.source,
            store_path=args.store,
            allow_duplicate=args.allow_duplicate,
        )
        write_markdown(store_path=args.store, markdown_path=args.markdown)
        if args.json:
            print(json.dumps({"created": created, "fragment": fragment}, indent=2))
        else:
            verb = "Added" if created else "Already present"
            print(f"{verb} fragment {fragment['id']}")
            print(f"Updated {args.markdown}")
        return 0

    if args.command == "rebase-ids":
        from value_investor.deferred_ideas_rebase import rebase_ids

        result = rebase_ids(args.base, store_path=args.store, apply=args.apply)
        if args.apply:
            write_markdown(store_path=args.store, markdown_path=args.markdown)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            for old, new in sorted(result["renames"].items()):
                print(f"{old} -> {new}")
            if not result["renames"]:
                print("No ID collisions with " + args.base)
            for rel in result["rewritten_files"]:
                print(f"Rewrote references in {rel}")
            for problem in result["problems"]:
                print(f"Problem: {problem}", file=sys.stderr)
            if not args.apply:
                print("Dry run — pass --apply to write.")
        return 1 if result["problems"] else 0

    if args.command == "check-ids":
        from value_investor.deferred_ideas_rebase import check_store_ids, load_store_at

        base = (
            load_store_at(args.base, repo=Path("."), store_path=args.store) if args.base else None
        )
        problems = check_store_ids(load_store(args.store), base)
        for problem in problems:
            print(f"deferred-ideas: {problem}", file=sys.stderr)
        if problems:
            print(
                f"Fix: git merge {args.base or 'origin/main'} && "
                f"ftse-defer rebase-ids --base {args.base or 'origin/main'} --apply",
                file=sys.stderr,
            )
            return 1
        print("deferred-ideas IDs OK")
        return 0

    if args.command == "fragment-status":
        row = set_fragment_status(args.fragment_id, args.status, store_path=args.store)
        write_markdown(store_path=args.store, markdown_path=args.markdown)
        print(f"Set fragment {row['id']} -> {row['status']}")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
