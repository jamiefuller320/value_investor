"""Deterministic loser-cohort snapshot cards (Tier 1 forensics, no agent)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.paper_fund import BUY_SIGNALS
from value_investor.research.store import ResearchStore
from value_investor.storage import read_json, write_json

CARDS_FILENAME = "loser_snapshot_cards.json"
CARDS_MD_FILENAME = "loser_snapshot_cards.md"

COHORT_AVOID = "avoid"
COHORT_FAILED_BUY_ALUMNI = "failed_buy_alumni"

ALL_FAMILIES = ("cheapness", "quality", "dividend", "garp", "risk")


def _parse_families(passed_families: str | None) -> list[str]:
    if not passed_families:
        return []
    return [part.strip().lower() for part in str(passed_families).split(",") if part.strip()]


def _failed_family_names(passed_families: str | None) -> list[str]:
    passed = set(_parse_families(passed_families))
    return [name for name in ALL_FAMILIES if name not in passed]


def _sector_context(reports: list[dict[str, Any]], sector: str | None) -> dict[str, Any]:
    if not sector:
        return {
            "sector": None,
            "sector_avoid_count": None,
            "sector_buy_count": None,
            "sector_peer_count": None,
            "sector_avoid_rate": None,
        }
    peers = [row for row in reports if str(row.get("sector") or "") == sector]
    avoid_count = sum(1 for row in peers if str(row.get("signal") or "") == "avoid")
    buy_count = sum(1 for row in peers if str(row.get("signal") or "").lower() in BUY_SIGNALS)
    peer_count = len(peers)
    return {
        "sector": sector,
        "sector_avoid_count": avoid_count,
        "sector_buy_count": buy_count,
        "sector_peer_count": peer_count,
        "sector_avoid_rate": round(avoid_count / peer_count, 4) if peer_count else None,
    }


def _opinion_flip_triggers(row: dict[str, Any]) -> list[str]:
    triggers: list[str] = []
    signal = str(row.get("signal") or "hold").lower()
    conviction = float(row.get("conviction_score") or 0)
    timing = str(row.get("timing_signal") or "").lower()
    failed_families = _failed_family_names(row.get("passed_families"))

    if signal == "avoid":
        triggers.append("screen signal upgrades above avoid")
    if conviction < 0.35:
        triggers.append("conviction >= 0.35")
    if timing == "wait":
        triggers.append("timing_signal != wait")
    if failed_families:
        triggers.append(f"passes {failed_families[0]} family (currently failed)")
    if float(row.get("data_quality_score") or 0) < 0.8:
        triggers.append("data_quality_score >= 0.8")
    verdict = str(row.get("research_verdict") or "").strip().lower()
    if verdict and verdict not in {"accumulate", "hold"}:
        triggers.append("research_verdict accumulate")
    return triggers[:5]


def _summary_lines(
    row: dict[str, Any], *, cohorts: list[str], sector_ctx: dict[str, Any]
) -> list[str]:
    signal = str(row.get("signal") or "hold").upper()
    conviction = float(row.get("conviction_score") or 0)
    timing = str(row.get("timing_signal") or "n/a")
    weeks = int(row.get("weeks_at_signal") or 0)
    trend = str(row.get("signal_trend") or "n/a")
    failed_families = _failed_family_names(row.get("passed_families"))
    passed = str(row.get("passed_families") or "none")
    lines = [
        (
            f"{signal} | conviction {conviction:.0%} | timing {timing} | "
            f"{weeks}w at signal ({trend})"
        ),
        f"Cohorts: {', '.join(cohorts)}",
        f"Families passed: {passed}"
        + (f" | failed: {', '.join(failed_families)}" if failed_families else ""),
    ]
    if sector_ctx.get("sector"):
        lines.append(
            f"Sector {sector_ctx['sector']}: {sector_ctx['sector_avoid_count']}/"
            f"{sector_ctx['sector_peer_count']} avoid"
        )
    action_note = str(row.get("action_note") or "").strip()
    if action_note:
        lines.append(f"Action note: {action_note[:160]}")
    return lines


def build_loser_snapshot_card(
    row: dict[str, Any],
    *,
    cohorts: list[str],
    has_research_memo: bool = False,
    reports: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build one deterministic snapshot card from a latest.json report row."""
    sector_ctx = _sector_context(reports or [], row.get("sector"))
    failed_models = list(row.get("failed_models") or [])[:8]
    model_failures = row.get("model_failures") or {}
    top_failure_reasons: list[str] = []
    for model_name in failed_models[:3]:
        reasons = model_failures.get(model_name) or []
        if reasons:
            top_failure_reasons.append(f"{model_name}: {reasons[0]}")

    return {
        "ticker": row.get("ticker"),
        "name": row.get("name"),
        "cohorts": cohorts,
        "screen": {
            "signal": row.get("signal"),
            "conviction_score": row.get("conviction_score"),
            "timing_signal": row.get("timing_signal"),
            "timing_score": row.get("timing_score"),
            "weeks_at_signal": row.get("weeks_at_signal"),
            "signal_trend": row.get("signal_trend"),
            "stability_label": row.get("stability_label"),
            "data_quality_score": row.get("data_quality_score"),
            "composite_score": row.get("composite_score"),
            "models_passed": row.get("models_passed"),
            "model_count": row.get("model_count"),
            "families_passed": row.get("passed_families"),
            "failed_families": _failed_family_names(row.get("passed_families")),
            "failed_models_sample": failed_models,
            "top_failure_reasons": top_failure_reasons,
        },
        "sector_context": sector_ctx,
        "research": {
            "has_memo": has_research_memo,
            "research_verdict": row.get("research_verdict"),
            "research_confidence": row.get("research_confidence"),
            "research_risk_level": row.get("research_risk_level"),
        },
        "opinion_flip_triggers": _opinion_flip_triggers(row),
        "summary_lines": _summary_lines(row, cohorts=cohorts, sector_ctx=sector_ctx),
    }


def select_loser_cohort_members(
    reports: list[dict[str, Any]],
    *,
    memo_tickers: set[str],
    include_avoid: bool = True,
    include_failed_buy_alumni: bool = True,
) -> dict[str, list[str]]:
    """Return ticker -> cohort labels. Scoped loser cohort only — not full index."""
    by_ticker: dict[str, list[str]] = {}
    for row in reports:
        ticker = str(row.get("ticker") or "").strip()
        if not ticker:
            continue
        signal = str(row.get("signal") or "hold").lower()
        cohorts: list[str] = []
        if include_avoid and signal == "avoid":
            cohorts.append(COHORT_AVOID)
        if include_failed_buy_alumni and ticker in memo_tickers and signal not in BUY_SIGNALS:
            cohorts.append(COHORT_FAILED_BUY_ALUMNI)
        if cohorts:
            by_ticker[ticker] = cohorts
    return by_ticker


def format_loser_snapshot_cards_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Loser snapshot cards",
        "",
        f"Generated: {payload.get('generated_at')}",
        f"Scope: {payload.get('scope_note')}",
        f"Card count: {payload.get('card_count')}",
        "",
    ]
    for card in payload.get("cards") or []:
        lines.append(f"## {card.get('ticker')} — {card.get('name')}")
        for summary_line in card.get("summary_lines") or []:
            lines.append(f"- {summary_line}")
        triggers = card.get("opinion_flip_triggers") or []
        if triggers:
            lines.append("- Opinion-flip triggers: " + "; ".join(triggers))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def run_loser_snapshot_cards(
    *,
    data_dir: Path = Path("docs/data"),
    include_avoid: bool = True,
    include_failed_buy_alumni: bool = True,
    run_at: datetime | None = None,
) -> dict[str, Any]:
    """
      Build loser-cohort snapshot cards from latest screen + research alumni.

      Does **not** scan the full index — only avoid-tier names and failed-buy alumni
    (names with a research memo that are no longer buy-tier).
    """
    data_dir = Path(data_dir)
    latest_path = data_dir / "latest.json"
    if not latest_path.exists():
        raise FileNotFoundError(f"Missing screen snapshot at {latest_path}")

    latest = read_json(latest_path)
    reports = list((latest or {}).get("reports") or [])
    if not reports:
        raise RuntimeError("latest.json has no reports")

    store = ResearchStore(data_dir)
    memo_tickers = {doc.ticker for doc in store.list_documents()}
    members = select_loser_cohort_members(
        reports,
        memo_tickers=memo_tickers,
        include_avoid=include_avoid,
        include_failed_buy_alumni=include_failed_buy_alumni,
    )

    by_ticker = {str(row.get("ticker")): row for row in reports}
    cards: list[dict[str, Any]] = []
    for ticker in sorted(members):
        row = by_ticker.get(ticker)
        if not row:
            continue
        cards.append(
            build_loser_snapshot_card(
                row,
                cohorts=members[ticker],
                has_research_memo=ticker in memo_tickers,
                reports=reports,
            )
        )

    effective_run_at = run_at or datetime.now(UTC)
    cohort_counts = {
        COHORT_AVOID: sum(1 for cohorts in members.values() if COHORT_AVOID in cohorts),
        COHORT_FAILED_BUY_ALUMNI: sum(
            1 for cohorts in members.values() if COHORT_FAILED_BUY_ALUMNI in cohorts
        ),
    }
    payload = {
        "schema_version": 1,
        "scope": "loser_snapshot_cards",
        "observe_only": True,
        "generated_at": effective_run_at.isoformat(),
        "screen_run_at": (latest or {}).get("run_at"),
        "scope_note": (
            "Avoid-tier screen names + failed-buy alumni (memo present, no longer buy-tier). "
            "Hold tier and full index excluded."
        ),
        "config": {
            "include_avoid": include_avoid,
            "include_failed_buy_alumni": include_failed_buy_alumni,
        },
        "card_count": len(cards),
        "cohort_counts": cohort_counts,
        "cards": cards,
    }

    cards_path = data_dir / CARDS_FILENAME
    md_path = data_dir / CARDS_MD_FILENAME
    write_json(cards_path, payload, compact=True)
    md_path.write_text(format_loser_snapshot_cards_markdown(payload), encoding="utf-8")
    return payload


__all__ = [
    "CARDS_FILENAME",
    "CARDS_MD_FILENAME",
    "COHORT_AVOID",
    "COHORT_FAILED_BUY_ALUMNI",
    "build_loser_snapshot_card",
    "format_loser_snapshot_cards_markdown",
    "run_loser_snapshot_cards",
    "select_loser_cohort_members",
]
