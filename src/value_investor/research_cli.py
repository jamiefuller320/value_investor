"""CLI for buy-tier deep research documents."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from value_investor.constituents import DEFAULT_UNIVERSE, VALID_UNIVERSES
from value_investor.cursor_api_key import resolve_cursor_api_key
from value_investor.research.format import format_director_shadow_text, format_research_text
from value_investor.research.runner import (
    DEFAULT_RESEARCH_ALUMNI_CAP,
    DEFAULT_RESEARCH_WEEKLY_CAP,
    run_research_for_strong_buys,
    select_research_targets,
)
from value_investor.summary import build_company_reports


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate or update deep research memos for strong buys and top buy-rated names "
            f"(weekly cap default {DEFAULT_RESEARCH_WEEKLY_CAP})"
        )
    )
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument(
        "--skip-screen",
        action="store_true",
        help="Reuse latest_signals.csv instead of re-running the screener",
    )
    parser.add_argument("--limit", type=int, default=None, help="Limit universe when screening")
    parser.add_argument(
        "--universe",
        choices=VALID_UNIVERSES,
        default=DEFAULT_UNIVERSE,
        help=f"Screening universe when not using --skip-screen (default: {DEFAULT_UNIVERSE})",
    )
    parser.add_argument(
        "--include-investment-trusts",
        action="store_true",
        help="Merge trusts into the operating-company screen (disables separate trust track)",
    )
    parser.add_argument(
        "--skip-trust-screen",
        action="store_true",
        help="Skip the separate investment-trust track when screening",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=(
            "Cursor model for research agent "
            "(default: CURSOR_RESEARCH_MODEL, else library policy, else composer-2.5)"
        ),
    )
    parser.add_argument(
        "--api-key",
        default=(resolve_cursor_api_key()[0] or None),
        help="Cursor API key (default: CURSOR_API_KEY_V2 then CURSOR_API_KEY)",
    )
    parser.add_argument(
        "--force-initial",
        action="store_true",
        help="Regenerate initial deep pass even if a memo already exists",
    )
    parser.add_argument(
        "--research-cap",
        type=int,
        default=DEFAULT_RESEARCH_WEEKLY_CAP,
        help=(
            f"Max active buy-tier memos per run "
            f"(strong buys first, then top buys; default {DEFAULT_RESEARCH_WEEKLY_CAP})"
        ),
    )
    parser.add_argument(
        "--alumni-cap",
        type=int,
        default=DEFAULT_RESEARCH_ALUMNI_CAP,
        help=(
            f"Max weekly updates for researched names that left the buy list "
            f"(oldest memos first; default {DEFAULT_RESEARCH_ALUMNI_CAP})"
        ),
    )
    parser.add_argument(
        "--no-continue-alumni",
        action="store_true",
        help="Do not refresh research for names that dropped off the buy list",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List eligible research targets without calling the research agent",
    )
    parser.add_argument(
        "--gap-fill",
        action="store_true",
        help=(
            "Run red-flag gap-fill loop from output/deep_analysis.txt instead of "
            "the normal buy-tier research selection"
        ),
    )
    parser.add_argument(
        "--gap-fill-cap",
        type=int,
        default=3,
        help="Max tickers for --gap-fill (default: 3)",
    )
    parser.add_argument(
        "--deepen-sources",
        action="store_true",
        help=(
            "Re-ingest filings with historical deepen for existing memo tickers "
            "(Companies House accounts years + RNS/PDF bodies). Does not call Cursor "
            "and does not backdate research revisions."
        ),
    )
    parser.add_argument(
        "--tickers",
        default="",
        help="Comma-separated tickers for --deepen-sources (default: all memos in output-dir)",
    )
    parser.add_argument(
        "--model-ab",
        metavar="TICKER",
        default=None,
        help=(
            "L88 pilot: run baseline vs challenger initial memos on one ticker "
            "(default composer-2.5 vs grok-4.6)"
        ),
    )
    parser.add_argument(
        "--baseline-model",
        default="composer-2.5",
        help="Baseline model for --model-ab (default: composer-2.5)",
    )
    parser.add_argument(
        "--challenger-model",
        default="grok-4.6",
        help="Challenger model for --model-ab (default: grok-4.6)",
    )
    parser.add_argument(
        "--ab-output-dir",
        type=Path,
        default=Path("docs/data/research_model_ab"),
        help="Output root for --model-ab runs (default: docs/data/research_model_ab)",
    )
    parser.add_argument(
        "--no-record-ab-spend",
        action="store_true",
        help="Do not record estimated spend for --model-ab in library policy",
    )
    parser.add_argument(
        "--director-worker",
        metavar="TICKER",
        default=None,
        help=(
            "Trial director–worker memo: Grok plans + synthesises, "
            "Composer executes bounded worker tasks"
        ),
    )
    parser.add_argument(
        "--director-model",
        default="grok-4.6",
        help="Director model for --director-worker (default: grok-4.6)",
    )
    parser.add_argument(
        "--worker-model",
        default="composer-2.5",
        help="Worker model for --director-worker (default: composer-2.5)",
    )
    parser.add_argument(
        "--dw-output-dir",
        type=Path,
        default=Path("docs/data/research_director_worker"),
        help="Output root for --director-worker runs",
    )
    parser.add_argument(
        "--max-worker-tasks",
        type=int,
        default=5,
        help="Max Composer worker tasks per --director-worker run (default: 5)",
    )
    parser.add_argument(
        "--reports-json",
        type=Path,
        default=Path("docs/data/latest.json"),
        help="Fallback report source when screening CSV is absent (default: docs/data/latest.json)",
    )
    parser.add_argument(
        "--no-record-dw-spend",
        action="store_true",
        help="Do not record estimated spend for --director-worker in library policy",
    )
    parser.add_argument(
        "--skip-dw-cap",
        action="store_true",
        help="Bypass weekly director–worker run cap (exploration/steady guard)",
    )
    parser.add_argument(
        "--skip-escalation-gate",
        action="store_true",
        help="Run --director-worker even when no escalation triggers fire",
    )
    parser.add_argument(
        "--escalation-check-only",
        action="store_true",
        help="With --director-worker: evaluate escalation triggers and exit (no agents)",
    )
    parser.add_argument(
        "--no-promote-baseline",
        action="store_true",
        help="Do not merge director baseline onto live research memo after --director-worker",
    )
    parser.add_argument(
        "--no-director-shadow",
        action="store_true",
        help="Disable observe-only director escalation logging on normal research runs",
    )
    parser.add_argument(
        "--escalation-candidates",
        action="store_true",
        help=(
            "List director escalation candidates for the current ISO week "
            "(approval queue; no agents)"
        ),
    )
    args = parser.parse_args(argv)

    if args.escalation_candidates:
        from value_investor.research.director_escalation_candidates import (
            DEFAULT_ESCALATION_CANDIDATES_PATH,
            aggregate_escalation_candidates,
            write_escalation_candidates,
        )
        from value_investor.research.format import format_director_escalation_candidates_text

        queue = aggregate_escalation_candidates()
        write_escalation_candidates(queue, path=DEFAULT_ESCALATION_CANDIDATES_PATH)
        preview = format_director_escalation_candidates_text(queue)
        if preview:
            print(preview)
        else:
            print("No director escalation candidates for the current week.")
        print(f"Wrote {DEFAULT_ESCALATION_CANDIDATES_PATH}")
        return 0

    if args.director_worker:
        from value_investor.agent_model_policy import DEFAULT_POLICY_PATH, load_policy
        from value_investor.research.director_baseline import evaluate_material_change
        from value_investor.research.director_escalation import evaluate_director_escalation
        from value_investor.research.director_promotion import promote_director_baseline_to_store
        from value_investor.research.director_worker import (
            load_report_from_latest,
            preview_director_worker_trial,
            run_director_worker_trial,
        )
        from value_investor.research.director_worker_cap import (
            check_director_worker_cap,
            record_director_worker_run,
        )
        from value_investor.research.gap_fill_sources import inspect_local_sources
        from value_investor.research.source_quality import score_research_sources
        from value_investor.research.store import ResearchStore

        report = load_report_from_latest(args.director_worker, args.reports_json)
        if report is None:
            print(
                f"Ticker {args.director_worker!r} not found in {args.reports_json}",
                file=sys.stderr,
            )
            return 1
        market = "ftse350" if args.universe.startswith("ftse") else args.universe
        store = ResearchStore(args.output_dir)
        existing_doc = store.load(report.ticker)
        sources_dir = store.sources_dir(report.ticker)
        inventory = inspect_local_sources(sources_dir) if sources_dir.exists() else {}
        source_counts = dict(existing_doc.source_counts) if existing_doc else {}
        source_quality = score_research_sources(
            source_counts=source_counts,
            inventory=inventory,
            question_outcomes=existing_doc.question_outcomes if existing_doc else None,
        )
        escalation = evaluate_director_escalation(
            report=report,
            existing_doc=existing_doc,
            inventory=inventory,
            source_quality=source_quality,
        )
        material = evaluate_material_change(
            baseline=existing_doc.director_baseline if existing_doc else None,
            report=report,
            inventory=inventory,
            source_counts=source_counts,
        )
        cap_status = check_director_worker_cap(
            report.ticker,
            policy_path=DEFAULT_POLICY_PATH,
        )
        if args.dry_run or args.escalation_check_only:
            preview = preview_director_worker_trial(
                report=report,
                primary_output_dir=args.output_dir,
                market=market,
                max_worker_tasks=args.max_worker_tasks,
            )
            plan = preview["task_plan"]
            label = "Escalation check" if args.escalation_check_only else "Director–worker dry-run"
            print(f"{label}: {report.name} ({report.ticker})")
            print(
                f"Escalation: {'yes' if escalation.should_escalate else 'no'} "
                f"({', '.join(escalation.triggers) or 'none'})"
            )
            for reason in escalation.reasons:
                print(f"  • {reason}")
            if existing_doc and existing_doc.director_baseline:
                print(
                    f"Material change vs baseline: "
                    f"{'yes' if material.material_change else 'no'} "
                    f"({', '.join(material.triggers) or 'none'})"
                )
            print(
                f"Cap: {cap_status.runs_this_week}/{cap_status.weekly_cap} "
                f"this week ({cap_status.phase}); "
                f"re-escalation={'yes' if cap_status.is_reescalation else 'no'}"
            )
            if not args.escalation_check_only:
                print(f"Estimated worker tasks: {preview['estimated_tasks']}")
                for task in plan.get("tasks") or []:
                    print(
                        f"  • [{task.get('type')}] {task.get('id')}: "
                        f"{task.get('target')} — {str(task.get('focus', ''))[:100]}"
                    )
            return 0
        if not escalation.should_escalate and not args.skip_escalation_gate:
            print("Director escalation gate: not triggered", file=sys.stderr)
            for reason in escalation.reasons:
                print(f"  • {reason}", file=sys.stderr)
            print("Use --skip-escalation-gate to run anyway.", file=sys.stderr)
            return 1
        if (
            existing_doc
            and existing_doc.director_baseline
            and not material.material_change
            and not args.skip_escalation_gate
        ):
            print("Director re-escalation gate: no material change since baseline", file=sys.stderr)
            for reason in material.reasons:
                print(f"  • {reason}", file=sys.stderr)
            print("Use --skip-escalation-gate to re-run anyway.", file=sys.stderr)
            return 1
        if not cap_status.allowed and not args.skip_dw_cap:
            print(cap_status.reason, file=sys.stderr)
            return 1
        if not args.api_key:
            print("CURSOR_API_KEY required for --director-worker", file=sys.stderr)
            return 1
        policy = load_policy(DEFAULT_POLICY_PATH)
        memo_usd = float((policy.get("ladder") or {}).get("estimated_memo_usd") or 0.4)
        print(
            f"Director–worker trial: {report.name} ({report.ticker}) — "
            f"director={args.director_model} worker={args.worker_model} "
            f"max_tasks={args.max_worker_tasks}"
        )
        print(
            f"Cap: {cap_status.runs_this_week + 1}/{cap_status.weekly_cap} "
            f"this week ({cap_status.phase}); "
            f"re-escalation={'yes' if cap_status.is_reescalation else 'no'}"
        )
        run = run_director_worker_trial(
            report=report,
            api_key=args.api_key,
            output_root=args.dw_output_dir,
            primary_output_dir=args.output_dir,
            director_model=args.director_model,
            worker_model=args.worker_model,
            market=market,
            max_worker_tasks=args.max_worker_tasks,
            memo_usd=memo_usd,
            record_spend=not args.no_record_dw_spend,
            policy_path=DEFAULT_POLICY_PATH,
        )
        if not args.skip_dw_cap:
            ledger_info = record_director_worker_run(
                ticker=report.ticker,
                run_id=run.run_id,
                policy_path=DEFAULT_POLICY_PATH,
            )
            tighten = ledger_info.get("auto_tighten") or {}
            if tighten.get("applied"):
                print(
                    "Auto-tighten: moved to steady phase "
                    f"(cap {tighten.get('steady_weekly_cap')}, "
                    f"re-escalation rate {tighten.get('reescalation_rate')})"
                )
        print(f"Workers completed: {len(run.worker_results)}")
        meta_count = len(run.task_plan.get("meta_reflection") or [])
        if meta_count:
            print(f"Meta-reflection items: {meta_count}")
        print(f"Rubric composite: {run.rubric.get('composite')}")
        print(f"Verdict: {run.document.research_verdict} ({run.document.research_confidence})")
        print(f"Est. cost: ${run.estimated_cost_usd:.2f}")
        print(f"Wrote {run.output_dir / 'research.md'}")
        if not args.no_promote_baseline:
            try:
                store = ResearchStore(args.output_dir)
                promoted = promote_director_baseline_to_store(
                    store=store,
                    director_doc=run.document,
                    run_id=run.run_id,
                    trial_output_dir=str(run.output_dir),
                )
                print(
                    f"Promoted director baseline to live memo "
                    f"({store.metadata_path(report.ticker)})"
                )
                if promoted.director_baseline.get("open_questions"):
                    print(
                        f"  Baseline open questions: "
                        f"{len(promoted.director_baseline['open_questions'])}"
                    )
            except ValueError as exc:
                print(f"Baseline promotion skipped: {exc}", file=sys.stderr)
        return 0

    if args.deepen_sources:
        from value_investor.research.deepen_sources import deepen_sources_for_memo_tickers

        ticker_list = [t.strip() for t in str(args.tickers).split(",") if t.strip()] or None
        result = deepen_sources_for_memo_tickers(
            output_dir=args.output_dir,
            tickers=ticker_list,
            market="ftse350" if args.universe.startswith("ftse") else args.universe,
        )
        print(
            f"Deepened sources for {len(result.deepened)} memo ticker(s); "
            f"skipped={len(result.skipped)} errors={len(result.errors)}"
        )
        for row in result.deepened:
            print(
                f"  • {row['ticker']}: filings={row.get('filings_total')} "
                f"with_body={row.get('filings_with_body')}"
            )
        for err in result.errors:
            print(f"  ! {err}", file=sys.stderr)
        print(f"Wrote {args.output_dir / 'deepen_sources_summary.json'}")
        return 1 if result.errors and not result.deepened else 0

    if args.skip_screen:
        signals_path = args.output_dir / "latest_signals.csv"
        model_results_path = args.output_dir / "latest_model_results.csv"
        if not signals_path.exists() or not model_results_path.exists():
            print("Missing output files; run ftse-screen first", file=sys.stderr)
            return 1
        signals = pd.read_csv(signals_path)
        model_results = pd.read_csv(model_results_path)
    else:
        from value_investor.pipeline import run_screen, write_outputs

        result = run_screen(
            limit=args.limit,
            output_dir=args.output_dir,
            universe=args.universe,
            include_investment_trusts=args.include_investment_trusts,
            screen_trusts=not args.skip_trust_screen,
        )
        write_outputs(result, args.output_dir)
        signals = result.signals
        model_results = result.model_results

    reports = build_company_reports(signals, model_results)

    if args.model_ab:
        from value_investor.agent_model_policy import DEFAULT_POLICY_PATH, load_policy
        from value_investor.research.model_ab import report_for_ticker, run_model_ab_compare

        report = report_for_ticker(reports, args.model_ab)
        if report is None:
            print(f"Ticker {args.model_ab!r} not found in latest screen output", file=sys.stderr)
            return 1
        if args.dry_run:
            print(
                f"Model A/B dry-run: {report.name} ({report.ticker}) "
                f"{args.baseline_model} vs {args.challenger_model}"
            )
            return 0
        if not args.api_key:
            print("CURSOR_API_KEY required for --model-ab", file=sys.stderr)
            return 1
        policy = load_policy(DEFAULT_POLICY_PATH)
        memo_usd = float((policy.get("ladder") or {}).get("estimated_memo_usd") or 0.4)
        market = "ftse350" if args.universe.startswith("ftse") else args.universe
        print(
            f"Model A/B: {report.name} ({report.ticker}) — "
            f"{args.baseline_model} vs {args.challenger_model}"
        )
        comparison = run_model_ab_compare(
            report=report,
            api_key=args.api_key,
            output_root=args.ab_output_dir,
            primary_output_dir=args.output_dir,
            baseline_model=args.baseline_model,
            challenger_model=args.challenger_model,
            market=market,
            memo_usd=memo_usd,
            record_spend=not args.no_record_ab_spend,
            policy_path=DEFAULT_POLICY_PATH,
        )
        print(f"Winner (rubric): {comparison.winner}")
        print(
            f"Composite: baseline={comparison.baseline.rubric.composite:.3f} "
            f"challenger={comparison.challenger.rubric.composite:.3f}"
        )
        print(f"Wrote {comparison.output_dir / 'comparison.md'}")
        return 0

    if args.gap_fill:
        from value_investor.deep_analysis import _parse_deep_analysis
        from value_investor.research.gap_fill import (
            extract_gap_fill_targets,
            run_red_flag_gap_fill,
        )
        from value_investor.storage import write_json

        analysis_path = args.output_dir / "deep_analysis.txt"
        if not analysis_path.exists():
            print(
                "Missing deep_analysis.txt; run ftse-email --deep-analysis first", file=sys.stderr
            )
            return 1
        deep_analysis = _parse_deep_analysis(analysis_path.read_text(encoding="utf-8"))
        targets = extract_gap_fill_targets(
            deep_analysis,
            reports,
            max_targets=int(args.gap_fill_cap),
        )
        print(f"Selected {len(targets)} gap-fill target(s) (cap={args.gap_fill_cap})")
        for target in targets:
            q0 = target.questions[0] if target.questions else ""
            print(f"  • {target.name} ({target.ticker}) — {q0[:120]}")
        if args.dry_run:
            return 0
        if not args.api_key:
            print("CURSOR_API_KEY required for research generation", file=sys.stderr)
            return 1
        model = args.model or os.environ.get("CURSOR_RESEARCH_MODEL") or "composer-2.5"
        print(f"Research model: {model}")
        gap_summary = run_red_flag_gap_fill(
            deep_analysis=deep_analysis,
            reports=reports,
            output_dir=args.output_dir,
            api_key=args.api_key,
            model=model,
            max_targets=int(args.gap_fill_cap),
            market="ftse350",
        )
        write_json(
            args.output_dir / "gap_fill_summary.json",
            {"run_at": datetime.now(UTC).isoformat(), **gap_summary.to_dict()},
            compact=True,
        )
        print(
            f"Gap-fill complete: created={gap_summary.created} "
            f"updated={gap_summary.updated} errors={len(gap_summary.errors)}"
        )
        for error in gap_summary.errors:
            print(f"  ! {error}", file=sys.stderr)
        return 1 if gap_summary.errors and not gap_summary.documents else 0

    store = ResearchStore(args.output_dir)
    active, alumni = select_research_targets(
        reports,
        store,
        weekly_cap=args.research_cap,
        continue_alumni=not args.no_continue_alumni,
        alumni_cap=args.alumni_cap,
    )
    targets = [*active, *alumni]
    strong_count = sum(1 for r in active if r.signal == "strong_buy")
    buy_count = sum(1 for r in active if r.signal == "buy")
    print(
        f"Selected {len(targets)} research target(s) "
        f"({strong_count} strong buy, {buy_count} buy, {len(alumni)} alumni; "
        f"caps active={args.research_cap} alumni={args.alumni_cap})"
    )

    if args.dry_run:
        for report in active:
            print(f"  • {report.name} ({report.ticker}) — {report.signal}")
        for report in alumni:
            print(f"  • {report.name} ({report.ticker}) — {report.signal} [alumni]")
        return 0

    if not args.api_key:
        print("CURSOR_API_KEY required for research generation", file=sys.stderr)
        return 1

    model = args.model or os.environ.get("CURSOR_RESEARCH_MODEL")
    if not model:
        try:
            from value_investor.agent_model_policy import research_model_id

            model = research_model_id()
        except Exception:  # noqa: BLE001
            model = "composer-2.5"
    print(f"Research model: {model}")

    summary = run_research_for_strong_buys(
        reports=reports,
        output_dir=args.output_dir,
        api_key=args.api_key,
        model=model,
        force_initial=args.force_initial,
        weekly_cap=args.research_cap,
        continue_alumni=not args.no_continue_alumni,
        alumni_cap=args.alumni_cap,
        director_shadow=not args.no_director_shadow,
    )

    summary_path = args.output_dir / "research_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    from value_investor.storage import write_json

    write_json(
        summary_path,
        {
            "run_at": datetime.now(UTC).isoformat(),
            "created": summary.created,
            "updated": summary.updated,
            "skipped": summary.skipped,
            "errors": summary.errors,
            "weekly_cap": args.research_cap,
            "alumni_cap": args.alumni_cap,
            "continue_alumni": not args.no_continue_alumni,
            "active_count": summary.active_count,
            "alumni_count": summary.alumni_count,
            "alumni_updated": summary.alumni_updated,
            "director_shadow": summary.director_shadow,
            "documents": [doc.to_dict() for doc in summary.documents],
        },
        compact=True,
    )

    preview = format_research_text(summary, summary.documents)
    if preview:
        print(preview)
    shadow_preview = format_director_shadow_text(summary.director_shadow)
    if shadow_preview:
        print()
        print(shadow_preview)

    from value_investor.research.director_escalation_candidates import (
        DEFAULT_ESCALATION_CANDIDATES_PATH,
        aggregate_escalation_candidates,
        write_escalation_candidates,
    )
    from value_investor.research.format import format_director_escalation_candidates_text

    queue = aggregate_escalation_candidates(run_entries=summary.director_shadow)
    if queue.candidates or summary.director_shadow:
        write_escalation_candidates(queue, path=DEFAULT_ESCALATION_CANDIDATES_PATH)
    candidates_preview = format_director_escalation_candidates_text(queue)
    if candidates_preview:
        print()
        print(candidates_preview)

    if summary.errors:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
