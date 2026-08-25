"""Hypothesis-first review for underwater holdings + portfolio loser feedback.

Value books already price in cheapness. A mark drawdown alone should not force an
exit — first ask whether the investment hypothesis still holds on the facts, then
treat the share of in-book losers as a selection-feedback and balancing metric.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BUY_SIGNALS = frozenset({"strong_buy", "buy"})
HARD_EXIT_SIGNALS = frozenset({"avoid"})
BROKEN_RESEARCH = frozenset({"sell", "avoid", "exit", "pass"})
SUPPORTIVE_RESEARCH = frozenset({"accumulate", "hold", "buy", "strong_buy"})

THESIS_INTACT = "intact"
THESIS_WEAKENING = "weakening"
THESIS_BROKEN = "broken"
THESIS_INSUFFICIENT = "insufficient_data"

ACTION_HOLD_TOLERATE = "hold_tolerate"
ACTION_WATCH_REVIEW = "watch_review"
ACTION_EXIT_CANDIDATE = "exit_candidate"
ACTION_INSUFFICIENT = "insufficient_data"

ALL_FAMILIES = ("cheapness", "quality", "dividend", "garp", "risk")

REVIEW_FILENAME = "hypothesis_integrity.json"
REVIEW_MD_FILENAME = "hypothesis_integrity.md"
ROLLUP_FILENAME = "learning_tracks_hypothesis_integrity.json"


@dataclass
class HypothesisIntegrityConfig:
    """Thresholds for thesis checks and portfolio loser tolerance."""

    underwater_pct: float = -0.05
    deep_underwater_pct: float = -0.15
    loser_share_tolerance: float = 0.40
    loser_nav_tolerance: float = 0.35
    min_data_quality: float = 0.55
    min_conviction_for_intact: float = 0.35
    intact_urgency_dampen: float = 0.18
    broken_urgency_boost: float = 0.28
    skip_underwater_urgency_when_intact: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> HypothesisIntegrityConfig:
        raw = data or {}
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known})


DEFAULT_HYPOTHESIS_CONFIG = HypothesisIntegrityConfig()


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def unrealized_gain_pct(*, mark: float | None, avg_cost: float) -> float | None:
    if mark is None or avg_cost <= 0:
        return None
    return (float(mark) - float(avg_cost)) / float(avg_cost)


def _parse_families(passed_families: str | list[str] | None) -> list[str]:
    if not passed_families:
        return []
    if isinstance(passed_families, list):
        return [str(part).strip().lower() for part in passed_families if str(part).strip()]
    return [part.strip().lower() for part in str(passed_families).split(",") if part.strip()]


def _failed_families(passed_families: str | list[str] | None) -> list[str]:
    passed = set(_parse_families(passed_families))
    return [name for name in ALL_FAMILIES if name not in passed]


def _screen_signal(row: dict[str, Any] | None, *, use_adjusted_signal: bool = False) -> str:
    row = row or {}
    if use_adjusted_signal:
        adjusted = row.get("adjusted_signal")
        if adjusted is not None and str(adjusted).strip():
            return str(adjusted).strip().lower()
    return str(row.get("signal") or "").strip().lower()


def _research_verdict(row: dict[str, Any] | None) -> str:
    row = row or {}
    for key in ("research_verdict", "research_action", "overlay_verdict"):
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip().lower()
    return ""


def assess_holding_hypothesis(
    *,
    ticker: str,
    mark: float | None,
    avg_cost: float,
    row: dict[str, Any] | None = None,
    use_adjusted_signal: bool = False,
    config: HypothesisIntegrityConfig | None = None,
) -> dict[str, Any]:
    """
    Ask whether the investment hypothesis still holds given current facts.

    Price drawdown alone does not break the thesis for a value holding.
    """
    cfg = config or DEFAULT_HYPOTHESIS_CONFIG
    row = row or {}
    gain = unrealized_gain_pct(mark=mark, avg_cost=avg_cost)
    underwater = gain is not None and gain <= cfg.underwater_pct
    deep_underwater = gain is not None and gain <= cfg.deep_underwater_pct

    signal = _screen_signal(row, use_adjusted_signal=use_adjusted_signal)
    timing = str(row.get("timing_signal") or "").strip().lower()
    conviction = float(row.get("conviction_score") or 0)
    data_quality = _optional_float(row.get("data_quality_score"))
    passed = _parse_families(row.get("passed_families"))
    failed = _failed_families(row.get("passed_families"))
    research = _research_verdict(row)
    cheapness_ok = "cheapness" in passed

    intact_reasons: list[str] = []
    weaken_reasons: list[str] = []
    broken_reasons: list[str] = []

    if signal in HARD_EXIT_SIGNALS:
        broken_reasons.append(f"screen signal is {signal}")
    elif signal and signal not in BUY_SIGNALS:
        weaken_reasons.append(f"left buy tier ({signal or 'blank'})")
    elif signal in BUY_SIGNALS:
        intact_reasons.append(f"still {signal}")

    if research in BROKEN_RESEARCH:
        broken_reasons.append(f"research verdict {research}")
    elif research in SUPPORTIVE_RESEARCH:
        intact_reasons.append(f"research {research}")
    elif research:
        weaken_reasons.append(f"research verdict {research}")

    if cheapness_ok:
        intact_reasons.append("cheapness family still passes")
    elif passed or failed:
        if signal in BUY_SIGNALS:
            weaken_reasons.append("cheapness family no longer passes")
        else:
            broken_reasons.append("cheapness lost and not in buy tier")

    if data_quality is not None and data_quality < cfg.min_data_quality:
        weaken_reasons.append(f"data_quality {data_quality:.2f} below floor")
    elif data_quality is not None:
        intact_reasons.append(f"data_quality {data_quality:.2f}")

    if conviction > 0 and conviction < cfg.min_conviction_for_intact:
        weaken_reasons.append(f"conviction {conviction:.0%} below intact floor")
    elif conviction >= cfg.min_conviction_for_intact:
        intact_reasons.append(f"conviction {conviction:.0%}")

    if timing == "wait" and underwater:
        weaken_reasons.append("timing=wait while underwater")

    if underwater and not (intact_reasons or weaken_reasons or broken_reasons):
        # Mark-only context: cannot judge thesis.
        status = THESIS_INSUFFICIENT
        action = ACTION_INSUFFICIENT
        primary_reasons = ["price drawdown with insufficient fact coverage"]
    elif broken_reasons:
        status = THESIS_BROKEN
        action = ACTION_EXIT_CANDIDATE
        primary_reasons = broken_reasons
    elif weaken_reasons and not intact_reasons:
        status = THESIS_WEAKENING
        action = ACTION_WATCH_REVIEW
        primary_reasons = weaken_reasons
    elif weaken_reasons and intact_reasons:
        status = THESIS_WEAKENING
        action = ACTION_WATCH_REVIEW
        primary_reasons = weaken_reasons + intact_reasons[:2]
    elif intact_reasons:
        status = THESIS_INTACT
        action = ACTION_HOLD_TOLERATE if underwater else ACTION_HOLD_TOLERATE
        primary_reasons = intact_reasons
        if underwater:
            primary_reasons = [
                "price drawdown alone does not invalidate value thesis",
                *intact_reasons,
            ]
    else:
        status = THESIS_INSUFFICIENT
        action = ACTION_INSUFFICIENT
        primary_reasons = ["insufficient screen/research facts to judge thesis"]

    if deep_underwater and status == THESIS_INTACT:
        # Still intact, but escalate review priority without forcing exit.
        action = ACTION_WATCH_REVIEW
        primary_reasons = [
            f"deep drawdown ({gain:+.1%}) — re-check facts; thesis still intact",
            *primary_reasons,
        ]

    return {
        "ticker": ticker,
        "name": str(row.get("name") or ticker),
        "thesis_status": status,
        "recommended_action": action,
        "underwater": underwater,
        "deep_underwater": deep_underwater,
        "unrealized_pct": round(gain, 4) if gain is not None else None,
        "mark": round(float(mark), 4) if mark is not None else None,
        "avg_cost": round(float(avg_cost), 4) if avg_cost else None,
        "signal": signal or None,
        "timing_signal": timing or None,
        "conviction_score": round(conviction, 4) if conviction else None,
        "data_quality_score": round(data_quality, 4) if data_quality is not None else None,
        "passed_families": passed,
        "failed_families": failed,
        "research_verdict": research or None,
        "reasons": primary_reasons[:6],
        "intact_reasons": intact_reasons[:6],
        "weaken_reasons": weaken_reasons[:6],
        "broken_reasons": broken_reasons[:6],
    }


def urgency_adjustment_for_hypothesis(
    thesis_status: str | None,
    *,
    config: HypothesisIntegrityConfig | None = None,
) -> float:
    """Signed delta to apply to exit_urgency from thesis status."""
    cfg = config or DEFAULT_HYPOTHESIS_CONFIG
    if thesis_status == THESIS_INTACT:
        return -abs(cfg.intact_urgency_dampen)
    if thesis_status == THESIS_BROKEN:
        return abs(cfg.broken_urgency_boost)
    if thesis_status == THESIS_WEAKENING:
        return 0.08
    return 0.0


def portfolio_loser_feedback(
    assessments: list[dict[str, Any]],
    *,
    position_values: dict[str, float] | None = None,
    config: HypothesisIntegrityConfig | None = None,
) -> dict[str, Any]:
    """
    Aggregate in-portfolio losers as a feedback metric against selection criteria.

    Tolerates a configured share of underwater names when theses remain intact.
    """
    cfg = config or DEFAULT_HYPOTHESIS_CONFIG
    values = position_values or {}
    holdings = [a for a in assessments if a.get("ticker")]
    n = len(holdings)
    losers = [a for a in holdings if a.get("underwater")]
    intact_losers = [a for a in losers if a.get("thesis_status") == THESIS_INTACT]
    broken_losers = [a for a in losers if a.get("thesis_status") == THESIS_BROKEN]
    weakening_losers = [a for a in losers if a.get("thesis_status") == THESIS_WEAKENING]

    total_nav = sum(max(0.0, float(values.get(str(a["ticker"]), 0) or 0)) for a in holdings)
    loser_nav = sum(max(0.0, float(values.get(str(a["ticker"]), 0) or 0)) for a in losers)
    loser_share = (len(losers) / n) if n else 0.0
    loser_nav_share = (loser_nav / total_nav) if total_nav > 0 else 0.0

    # Family failure rates among losers vs non-losers — selection feedback.
    def _family_fail_rates(rows: list[dict[str, Any]]) -> dict[str, float]:
        if not rows:
            return {family: 0.0 for family in ALL_FAMILIES}
        counts = {family: 0 for family in ALL_FAMILIES}
        for row in rows:
            for family in row.get("failed_families") or []:
                key = str(family).lower()
                if key in counts:
                    counts[key] += 1
        return {family: round(counts[family] / len(rows), 4) for family in ALL_FAMILIES}

    non_losers = [a for a in holdings if not a.get("underwater")]
    loser_fail = _family_fail_rates(losers)
    winner_fail = _family_fail_rates(non_losers)
    selection_flags: list[str] = []
    for family in ALL_FAMILIES:
        delta = loser_fail[family] - winner_fail[family]
        if losers and delta >= 0.35:
            selection_flags.append(
                f"{family} fails more often among losers "
                f"({loser_fail[family]:.0%} vs {winner_fail[family]:.0%})"
            )

    within_count_tolerance = loser_share <= cfg.loser_share_tolerance
    within_nav_tolerance = loser_nav_share <= cfg.loser_nav_tolerance
    within_tolerance = within_count_tolerance and within_nav_tolerance

    balancing_hint = "maintain"
    if broken_losers:
        balancing_hint = "rotate_broken_first"
    elif not within_tolerance and weakening_losers:
        balancing_hint = "trim_weakening_losers"
    elif not within_tolerance and intact_losers:
        balancing_hint = "hold_intact_review_selection"
    elif within_tolerance and intact_losers:
        balancing_hint = "tolerate_intact_losers"

    return {
        "holding_count": n,
        "loser_count": len(losers),
        "loser_share": round(loser_share, 4),
        "loser_nav_share": round(loser_nav_share, 4),
        "loser_share_tolerance": cfg.loser_share_tolerance,
        "loser_nav_tolerance": cfg.loser_nav_tolerance,
        "within_tolerance": within_tolerance,
        "intact_loser_count": len(intact_losers),
        "weakening_loser_count": len(weakening_losers),
        "broken_loser_count": len(broken_losers),
        "family_fail_rate_losers": loser_fail,
        "family_fail_rate_non_losers": winner_fail,
        "selection_feedback_flags": selection_flags,
        "balancing_hint": balancing_hint,
        "note": (
            "Value books should tolerate a share of underwater names when thesis "
            "facts remain intact; use broken/weakening losers for rotation and "
            "selection feedback — not crude mark stops."
        ),
    }


def format_hypothesis_integrity_markdown(payload: dict[str, Any]) -> str:
    feedback = payload.get("portfolio_feedback") or {}
    lines = [
        "# Hypothesis integrity (in-portfolio)",
        "",
        f"Track: `{payload.get('track_id')}` · updated {payload.get('updated_at')}",
        "",
        "## Portfolio loser feedback",
        "",
        (
            f"- Losers: **{feedback.get('loser_count', 0)}** / "
            f"{feedback.get('holding_count', 0)} "
            f"({float(feedback.get('loser_share') or 0):.0%} count, "
            f"{float(feedback.get('loser_nav_share') or 0):.0%} NAV)"
        ),
        (
            f"- Tolerance: count ≤ {float(feedback.get('loser_share_tolerance') or 0):.0%}, "
            f"NAV ≤ {float(feedback.get('loser_nav_tolerance') or 0):.0%} → "
            f"{'within' if feedback.get('within_tolerance') else 'outside'} band"
        ),
        f"- Balancing hint: `{feedback.get('balancing_hint')}`",
    ]
    flags = feedback.get("selection_feedback_flags") or []
    if flags:
        lines.append("- Selection feedback:")
        for flag in flags:
            lines.append(f"  - {flag}")
    lines.extend(["", "## Holding reviews", ""])
    for card in payload.get("holdings") or []:
        gain = card.get("unrealized_pct")
        gain_txt = f"{gain:+.1%}" if isinstance(gain, (int, float)) else "n/a"
        lines.append(
            f"### {card.get('ticker')} — {card.get('thesis_status')} / "
            f"{card.get('recommended_action')} ({gain_txt})"
        )
        for reason in card.get("reasons") or []:
            lines.append(f"- {reason}")
        lines.append("")
    if not (payload.get("holdings") or []):
        lines.append("_No holdings to review._")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def run_hypothesis_integrity_pass(
    *,
    output_dir: Path,
    fund: Any,
    track_id: str,
    candidates: list[dict[str, Any]],
    prices_by_ticker: dict[str, float] | None = None,
    use_adjusted_signal: bool = False,
    as_of: str | datetime | None = None,
    config: HypothesisIntegrityConfig | None = None,
) -> dict[str, Any]:
    """Build observe-only hypothesis cards + loser feedback for one paper track."""
    cfg = config or DEFAULT_HYPOTHESIS_CONFIG
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    by_ticker = {str(row.get("ticker")): row for row in candidates if row.get("ticker") is not None}
    prices = dict(prices_by_ticker or {})
    when = (
        as_of.isoformat()
        if isinstance(as_of, datetime)
        else str(as_of or datetime.now(UTC).isoformat())
    )

    assessments: list[dict[str, Any]] = []
    position_values: dict[str, float] = {}
    holdings = getattr(fund, "holdings", {}) or {}
    for ticker, position in holdings.items():
        mark = prices.get(ticker)
        if mark is None or mark <= 0:
            mark = _optional_float(getattr(position, "avg_cost", None))
        avg_cost = float(getattr(position, "avg_cost", 0) or 0)
        shares = float(getattr(position, "shares", 0) or 0)
        if mark is not None and shares > 0:
            position_values[str(ticker)] = shares * float(mark)
        assessments.append(
            assess_holding_hypothesis(
                ticker=str(ticker),
                mark=float(mark) if mark is not None else None,
                avg_cost=avg_cost,
                row=by_ticker.get(str(ticker)),
                use_adjusted_signal=use_adjusted_signal,
                config=cfg,
            )
        )

    assessments.sort(
        key=lambda row: (
            0 if row.get("thesis_status") == THESIS_BROKEN else 1,
            0 if row.get("underwater") else 1,
            float(row.get("unrealized_pct") or 0),
        )
    )
    feedback = portfolio_loser_feedback(assessments, position_values=position_values, config=cfg)
    payload = {
        "schema_version": 1,
        "scope": "hypothesis_integrity",
        "observe_only": True,
        "track_id": track_id,
        "updated_at": datetime.now(UTC).isoformat(),
        "as_of": when,
        "config": cfg.to_dict(),
        "holding_count": len(assessments),
        "underwater_count": sum(1 for a in assessments if a.get("underwater")),
        "thesis_status_counts": {
            status: sum(1 for a in assessments if a.get("thesis_status") == status)
            for status in (
                THESIS_INTACT,
                THESIS_WEAKENING,
                THESIS_BROKEN,
                THESIS_INSUFFICIENT,
            )
        },
        "portfolio_feedback": feedback,
        "holdings": assessments,
        "note": (
            "Hypothesis-first underwater review. Does not auto-sell. "
            "Feeds exit_urgency dampening/boost and portfolio balancing hints."
        ),
    }
    (output_dir / REVIEW_FILENAME).write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / REVIEW_MD_FILENAME).write_text(
        format_hypothesis_integrity_markdown(payload), encoding="utf-8"
    )
    return payload


def summarize_learning_tracks_hypothesis_integrity(base_dir: Path) -> dict[str, Any]:
    from value_investor.paper_automation import learning_track_dirs

    base_dir = Path(base_dir)
    tracks: dict[str, Any] = {}
    for track_id, track_dir in learning_track_dirs(base_dir).items():
        path = track_dir / REVIEW_FILENAME
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        feedback = payload.get("portfolio_feedback") or {}
        tracks[track_id] = {
            "updated_at": payload.get("updated_at"),
            "holding_count": payload.get("holding_count"),
            "underwater_count": payload.get("underwater_count"),
            "thesis_status_counts": payload.get("thesis_status_counts"),
            "loser_share": feedback.get("loser_share"),
            "within_tolerance": feedback.get("within_tolerance"),
            "balancing_hint": feedback.get("balancing_hint"),
            "selection_feedback_flags": feedback.get("selection_feedback_flags"),
            "broken_loser_count": feedback.get("broken_loser_count"),
            "intact_loser_count": feedback.get("intact_loser_count"),
        }

    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "observe_only": True,
        "tracks": tracks,
        "note": (
            "In-portfolio hypothesis integrity + loser-tolerance feedback. "
            "Pair with exit_timing hold-recovery and loser_snapshot_cards."
        ),
    }


__all__ = [
    "ACTION_EXIT_CANDIDATE",
    "ACTION_HOLD_TOLERATE",
    "ACTION_INSUFFICIENT",
    "ACTION_WATCH_REVIEW",
    "DEFAULT_HYPOTHESIS_CONFIG",
    "HypothesisIntegrityConfig",
    "REVIEW_FILENAME",
    "REVIEW_MD_FILENAME",
    "ROLLUP_FILENAME",
    "THESIS_BROKEN",
    "THESIS_INSUFFICIENT",
    "THESIS_INTACT",
    "THESIS_WEAKENING",
    "assess_holding_hypothesis",
    "format_hypothesis_integrity_markdown",
    "portfolio_loser_feedback",
    "run_hypothesis_integrity_pass",
    "summarize_learning_tracks_hypothesis_integrity",
    "urgency_adjustment_for_hypothesis",
]
