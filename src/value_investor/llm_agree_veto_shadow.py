"""Observe-only algo → LLM agree/veto shadow cards (never blocks fills).

Pinned learning question: when the algo proposes sell / hold / rebuy, would an
evidence-citing agree/veto disagree often enough to justify a later hard veto
on the live capital path?

Default judge is a deterministic evidence heuristic that cites screen / rank /
research fields already on the decision trail. Schema is LLM-ready
(``judge_backend=llm``) but paper-auto does not call an LLM (N24). Live
influence stays fail-closed without durable evidence (N173 / project principle).
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
STORE_FILENAME = "llm_agree_veto_shadow.json"
REVIEW_FILENAME = "llm_agree_veto_shadow_review.json"
ROLLUP_FILENAME = "learning_tracks_llm_agree_veto.json"
PASS_KEY = "llm_agree_veto_shadow"

BUYISH = frozenset({"buy", "strong_buy"})
DEFAULT_RANK_DROP_EXIT_MIN = 3
KEEP_CARDS = 400

LEARNING_QUESTION = (
    "When the algo proposes sell/hold/rebuy, would an evidence-citing agree/veto "
    "disagree often enough to justify a later hard veto on the live capital path?"
)

PRINCIPLE = (
    "Any LLM influence on a live capital/decision path must record durable "
    "justifying evidence in the decision trail; no silent LLM discretion. "
    "This shadow is observe-only (influences_live=false) until a promotion gate."
)


@dataclass
class EvidenceCitation:
    kind: str
    source: str
    detail: str
    value: Any = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.value is None:
            payload.pop("value", None)
        return payload


@dataclass
class AgreeVetoCard:
    ticker: str
    name: str
    algo_action: str
    algo_reason: str
    shadow_verdict: str  # agree | veto | abstain
    reasons: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    judge_backend: str = "evidence_heuristic"
    influences_live: bool = False
    observe_only: bool = True
    track_id: str = "rules"
    logged_at: str | None = None
    proposal_id: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "name": self.name,
            "algo_action": self.algo_action,
            "algo_reason": self.algo_reason,
            "shadow_verdict": self.shadow_verdict,
            "reasons": list(self.reasons),
            "evidence": list(self.evidence),
            "judge_backend": self.judge_backend,
            "influences_live": False,  # hard: this instrument never influences live
            "observe_only": True,
            "track_id": self.track_id,
            "logged_at": self.logged_at,
            "proposal_id": self.proposal_id,
            "meta": dict(self.meta),
            "schema_version": SCHEMA_VERSION,
        }


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _signal_of(row: dict[str, Any] | None) -> str:
    if not row:
        return ""
    adjusted = str(row.get("adjusted_signal") or "").strip()
    if adjusted:
        return adjusted.lower()
    return str(row.get("signal") or "").strip().lower()


def _candidate_index(candidates: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    mapped: dict[str, dict[str, Any]] = {}
    for row in candidates:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").strip()
        if ticker:
            mapped[ticker] = row
    return mapped


def _conviction_ranks(
    candidates: list[dict[str, Any]], *, use_adjusted_signal: bool = False
) -> dict[str, int]:
    """1-based ranks among buyish names (higher rank number = worse)."""
    rows: list[tuple[float, str]] = []
    for row in candidates:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").strip()
        if not ticker:
            continue
        signal = (
            str(row.get("adjusted_signal") or row.get("signal") or "").strip().lower()
            if use_adjusted_signal
            else str(row.get("signal") or "").strip().lower()
        )
        if signal not in BUYISH:
            continue
        conviction = float(row.get("conviction_score") or 0.0)
        rows.append((-conviction, ticker))
    rows.sort()
    return {ticker: idx + 1 for idx, (_, ticker) in enumerate(rows)}


def _cite(kind: str, source: str, detail: str, value: Any = None) -> dict[str, Any]:
    return EvidenceCitation(kind=kind, source=source, detail=detail, value=value).to_dict()


def has_justifying_evidence(card: dict[str, Any] | AgreeVetoCard) -> bool:
    """True when structured reasons and at least one evidence citation exist."""
    if isinstance(card, AgreeVetoCard):
        reasons = card.reasons
        evidence = card.evidence
    else:
        reasons = list(card.get("reasons") or [])
        evidence = list(card.get("evidence") or [])
    return bool(reasons) and bool(evidence)


def authorize_live_llm_influence(card: dict[str, Any] | AgreeVetoCard) -> bool:
    """Fail-closed gate: live influence requires durable evidence + explicit flag.

    The observe shadow always returns False. Call this before any future hard
    veto path can mutate fills.
    """
    if isinstance(card, AgreeVetoCard):
        wants_live = bool(card.influences_live) and not bool(card.observe_only)
        payload = card.to_dict()
    else:
        wants_live = bool(card.get("influences_live")) and not bool(card.get("observe_only", True))
        payload = card
    if not wants_live:
        return False
    return has_justifying_evidence(payload)


def extract_algo_proposals(
    *,
    plan: dict[str, Any] | None,
    trades: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Normalize algo sell / hold / rebuy(+buy) proposals from plan + trades."""
    plan = plan or {}
    proposals: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def _add(action: str, row: dict[str, Any]) -> None:
        ticker = str(row.get("ticker") or "").strip()
        if not ticker:
            return
        key = (ticker, action)
        if key in seen:
            return
        seen.add(key)
        proposals.append(
            {
                "ticker": ticker,
                "name": str(row.get("name") or ticker),
                "algo_action": action,
                "algo_reason": str(row.get("reason") or row.get("note") or action),
                "source_row": row,
            }
        )

    for key, action in (
        ("exits", "sell"),
        ("holds", "hold"),
        ("buys", "buy"),
        ("skipped", "rebuy_skip"),
    ):
        for row in plan.get(key) or []:
            if isinstance(row, dict):
                _add(action, row)

    for trade in trades or []:
        if not isinstance(trade, dict):
            continue
        side = str(trade.get("side") or "").strip().lower()
        ticker = str(trade.get("ticker") or "").strip()
        if not ticker:
            continue
        if side == "sell" and bool(trade.get("position_closed")):
            _add(
                "sell",
                {
                    "ticker": ticker,
                    "name": trade.get("name") or ticker,
                    "reason": trade.get("note") or "Automated exit",
                    **trade,
                },
            )
        elif side == "buy":
            # Rebuy vs new sleeve is distinguished in the judge via holdings meta.
            action = "rebuy" if trade.get("is_rebuy") else "buy"
            note = str(trade.get("note") or "")
            if "re-entry" in note.lower() or "rebuy" in note.lower():
                action = "rebuy"
            _add(
                action,
                {
                    "ticker": ticker,
                    "name": trade.get("name") or ticker,
                    "reason": note or "Automated buy",
                    **trade,
                },
            )

    return proposals


def judge_proposal(
    proposal: dict[str, Any],
    *,
    candidate: dict[str, Any] | None,
    buy_ranks: dict[str, int],
    entry_ranks: dict[str, int] | None = None,
    holdings_before: set[str] | None = None,
    rank_drop_exit_min: int = DEFAULT_RANK_DROP_EXIT_MIN,
    track_id: str = "rules",
    logged_at: str | None = None,
    judge_backend: str = "evidence_heuristic",
) -> AgreeVetoCard:
    """Evidence-citing agree/veto for one algo proposal (observe-only)."""
    ticker = str(proposal.get("ticker") or "")
    name = str(proposal.get("name") or ticker)
    action = str(proposal.get("algo_action") or "").strip().lower()
    algo_reason = str(proposal.get("algo_reason") or "")
    entry_ranks = entry_ranks or {}
    holdings_before = holdings_before or set()
    signal = _signal_of(candidate)
    still_buyish = signal in BUYISH
    current_rank = buy_ranks.get(ticker)
    entry_rank = entry_ranks.get(ticker)
    if entry_rank is None and current_rank is not None:
        entry_rank = current_rank
    rank_drop = None
    if current_rank is not None and entry_rank is not None:
        rank_drop = int(current_rank) - int(entry_rank)
    research_verdict = (
        str((candidate or {}).get("research_verdict") or "").strip().lower() if candidate else ""
    )
    conviction = (candidate or {}).get("conviction_score")

    evidence: list[dict[str, Any]] = [
        _cite("algo_reason", "plan_or_trade", algo_reason or action),
    ]
    if signal:
        evidence.append(
            _cite("screen_signal", "candidates", "Effective signal at decision time", signal)
        )
    if current_rank is not None:
        evidence.append(
            _cite(
                "conviction_rank",
                "candidates",
                "1-based conviction rank among buyish names",
                current_rank,
            )
        )
    if entry_rank is not None:
        evidence.append(
            _cite(
                "entry_rank",
                "rebalance_state",
                "Conviction rank recorded at sleeve entry",
                entry_rank,
            )
        )
    if rank_drop is not None:
        evidence.append(
            _cite(
                "rank_drop",
                "derived",
                f"current_rank − entry_rank (hold gate < {rank_drop_exit_min})",
                rank_drop,
            )
        )
    if research_verdict:
        evidence.append(
            _cite(
                "research_verdict",
                "candidates",
                "Research overlay verdict at decision time",
                research_verdict,
            )
        )
    if conviction is not None:
        evidence.append(
            _cite(
                "conviction_score",
                "candidates",
                "Conviction score at decision time",
                conviction,
            )
        )
    evidence.append(
        _cite(
            "still_buyish",
            "derived",
            "Name remains buy/strong_buy on the decision screen",
            still_buyish,
        )
    )

    reasons: list[str] = []
    verdict = "abstain"

    if action == "sell":
        if still_buyish and rank_drop is not None and rank_drop < max(1, rank_drop_exit_min):
            verdict = "veto"
            reasons.append(
                "Capacity-bump risk: still buyish with insufficient rank drop — "
                "prefer hold over churn sell."
            )
        elif still_buyish and current_rank is None:
            verdict = "abstain"
            reasons.append("Still buyish but rank unavailable — abstain without inventing.")
        elif not still_buyish:
            verdict = "agree"
            reasons.append("Left buy cohort (signal not buy/strong_buy) — sell looks decisive.")
        elif rank_drop is not None and rank_drop >= max(1, rank_drop_exit_min):
            verdict = "agree"
            reasons.append(
                f"Rank drop {rank_drop} ≥ {rank_drop_exit_min} — cohort leave looks decisive."
            )
        else:
            verdict = "abstain"
            reasons.append("Sell proposal lacks clear leave-buy-cohort evidence — abstain.")
    elif action in {"hold", "rebuy_skip"}:
        if research_verdict in {"avoid", "sell", "reduce"}:
            verdict = "veto"
            reasons.append(
                f"Research verdict '{research_verdict}' conflicts with hold/skip — "
                "review for thesis break."
            )
        elif still_buyish or action == "rebuy_skip":
            verdict = "agree"
            reasons.append(
                "Hold/skip aligned with still-buyish or explicit rebuy block — "
                "consistent with low-churn sell meaning."
            )
        else:
            verdict = "abstain"
            reasons.append("Hold while not buyish — needs richer inputs; abstain.")
    elif action in {"buy", "rebuy"}:
        was_held = ticker in holdings_before
        if action == "rebuy" or (was_held is False and "cooldown" in algo_reason.lower()):
            if "cooldown" in algo_reason.lower() or "still-in-candidates" in algo_reason.lower():
                verdict = "agree"
                reasons.append("Rebuy already blocked by algo gate — agree with brake.")
            elif still_buyish:
                verdict = "abstain"
                reasons.append(
                    "Rebuy while still buyish — mark for review (never-left-candidates risk)."
                )
            else:
                verdict = "agree"
                reasons.append("Rebuy after leaving buy cohort — agree.")
        elif research_verdict in {"avoid", "sell"}:
            verdict = "veto"
            reasons.append(
                f"Buy conflicts with research verdict '{research_verdict}' — shadow veto."
            )
        elif still_buyish:
            verdict = "agree"
            reasons.append("Buy into buyish target set — agree with algo selection.")
        else:
            verdict = "abstain"
            reasons.append("Buy while not buyish — abstain.")
    else:
        reasons.append(f"Unrecognized algo action '{action}' — abstain.")

    if not reasons:
        reasons.append("No decisive agree/veto signal — abstain.")

    return AgreeVetoCard(
        ticker=ticker,
        name=name,
        algo_action=action,
        algo_reason=algo_reason,
        shadow_verdict=verdict,
        reasons=reasons,
        evidence=evidence,
        judge_backend=judge_backend,
        influences_live=False,
        observe_only=True,
        track_id=track_id,
        logged_at=logged_at or _utcnow(),
        proposal_id=f"{track_id}:{ticker}:{action}:{logged_at or _utcnow()}",
        meta={
            "still_buyish": still_buyish,
            "rank_drop": rank_drop,
            "rank_drop_exit_min": int(rank_drop_exit_min),
            "research_verdict": research_verdict or None,
            "learning_question": LEARNING_QUESTION,
        },
    )


def build_shadow_pass(
    *,
    track_id: str,
    plan: dict[str, Any] | None,
    trades: list[dict[str, Any]] | None,
    candidates: list[dict[str, Any]],
    holdings_before: list[dict[str, Any]] | None = None,
    rebalance_state_before: dict[str, Any] | None = None,
    use_adjusted_signal: bool = False,
    rank_drop_exit_min: int = DEFAULT_RANK_DROP_EXIT_MIN,
    as_of: str | None = None,
    judge_backend: str = "evidence_heuristic",
) -> dict[str, Any]:
    """Build observe-only agree/veto cards for one paper-auto pass."""
    logged_at = as_of or _utcnow()
    by_ticker = _candidate_index(candidates)
    buy_ranks = _conviction_ranks(candidates, use_adjusted_signal=use_adjusted_signal)
    entry_ranks_raw = (rebalance_state_before or {}).get("entry_candidate_rank") or {}
    entry_ranks = {
        str(k): int(v) for k, v in entry_ranks_raw.items() if str(k).strip() and v is not None
    }
    held = {
        str(row.get("ticker") or "").strip()
        for row in (holdings_before or [])
        if isinstance(row, dict) and str(row.get("ticker") or "").strip()
    }
    proposals = extract_algo_proposals(plan=plan, trades=trades)
    cards = [
        judge_proposal(
            proposal,
            candidate=by_ticker.get(str(proposal["ticker"])),
            buy_ranks=buy_ranks,
            entry_ranks=entry_ranks,
            holdings_before=held,
            rank_drop_exit_min=rank_drop_exit_min,
            track_id=track_id,
            logged_at=logged_at,
            judge_backend=judge_backend,
        ).to_dict()
        for proposal in proposals
    ]
    # Fail-closed strip: never allow influences_live on this instrument.
    for card in cards:
        card["influences_live"] = False
        card["observe_only"] = True
        if not has_justifying_evidence(card):
            card["shadow_verdict"] = "abstain"
            card.setdefault("reasons", []).append(
                "Missing justifying evidence — fail-closed to abstain (no live effect)."
            )

    counts = {"agree": 0, "veto": 0, "abstain": 0}
    by_action: dict[str, dict[str, int]] = {}
    for card in cards:
        v = str(card.get("shadow_verdict") or "abstain")
        counts[v] = counts.get(v, 0) + 1
        action = str(card.get("algo_action") or "other")
        bucket = by_action.setdefault(action, {"agree": 0, "veto": 0, "abstain": 0})
        bucket[v] = bucket.get(v, 0) + 1

    return {
        "schema_version": SCHEMA_VERSION,
        "track_id": track_id,
        "generated_at": logged_at,
        "observe_only": True,
        "influences_live": False,
        "judge_backend": judge_backend,
        "learning_question": LEARNING_QUESTION,
        "principle": PRINCIPLE,
        "proposal_count": len(proposals),
        "card_count": len(cards),
        "verdict_counts": counts,
        "by_algo_action": by_action,
        "cards": cards,
        "note": (
            "Observe-only agree/veto shadow — never blocks fills. "
            "still_in_buy_set remains the algo capital-path twin; this is a "
            "parallel review layer."
        ),
    }


def load_store(path: Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {
            "schema_version": SCHEMA_VERSION,
            "records": [],
            "observe_only": True,
            "influences_live": False,
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {
            "schema_version": SCHEMA_VERSION,
            "records": [],
            "observe_only": True,
            "influences_live": False,
            "error": "invalid_json",
        }
    if not isinstance(payload, dict):
        return {
            "schema_version": SCHEMA_VERSION,
            "records": [],
            "observe_only": True,
            "influences_live": False,
        }
    payload.setdefault("records", [])
    payload["observe_only"] = True
    payload["influences_live"] = False
    return payload


def save_store(path: Path, store: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    store = dict(store)
    store["schema_version"] = SCHEMA_VERSION
    store["observe_only"] = True
    store["influences_live"] = False
    records = list(store.get("records") or [])
    store["records"] = records[-KEEP_CARDS:]
    path.write_text(json.dumps(store, indent=2) + "\n", encoding="utf-8")


def build_review(pass_payload: dict[str, Any], *, track_id: str) -> dict[str, Any]:
    cards = [c for c in (pass_payload.get("cards") or []) if isinstance(c, dict)]
    veto_sells = [
        c for c in cards if c.get("algo_action") == "sell" and c.get("shadow_verdict") == "veto"
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "track_id": track_id,
        "generated_at": pass_payload.get("generated_at") or _utcnow(),
        "observe_only": True,
        "influences_live": False,
        "judge_backend": pass_payload.get("judge_backend") or "evidence_heuristic",
        "learning_question": LEARNING_QUESTION,
        "card_count": len(cards),
        "verdict_counts": pass_payload.get("verdict_counts") or {},
        "by_algo_action": pass_payload.get("by_algo_action") or {},
        "veto_sell_count": len(veto_sells),
        "veto_sell_tickers": [str(c.get("ticker")) for c in veto_sells],
        "promotion_gate": {
            "ready_for_hard_veto": False,
            "requires": [
                "Thick disagreement cohort vs still_in_buy_set twin marks",
                "Evidence schema present on every live-bound card (fail-closed)",
                "Explicit cold-start / epoch promotion — never mid-flight Suite A edit",
                "Suite B framing before treating as adoption truth",
            ],
            "note": (
                "Hard veto stays parked (N173) until disagreement marks justify it. "
                "Shadow cards never change fills."
            ),
        },
        "note": pass_payload.get("note"),
    }


def run_llm_agree_veto_shadow_pass(
    *,
    output_dir: Path,
    track_id: str,
    plan: dict[str, Any] | None,
    trades: list[dict[str, Any]] | None,
    candidates: list[dict[str, Any]],
    holdings_before: list[dict[str, Any]] | None = None,
    rebalance_state_before: dict[str, Any] | None = None,
    use_adjusted_signal: bool = False,
    rank_drop_exit_min: int = DEFAULT_RANK_DROP_EXIT_MIN,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Persist shadow cards + review under a track dir; return pass payload."""
    output_dir = Path(output_dir)
    pass_payload = build_shadow_pass(
        track_id=track_id,
        plan=plan,
        trades=trades,
        candidates=candidates,
        holdings_before=holdings_before,
        rebalance_state_before=rebalance_state_before,
        use_adjusted_signal=use_adjusted_signal,
        rank_drop_exit_min=rank_drop_exit_min,
        as_of=as_of,
    )
    store_path = output_dir / STORE_FILENAME
    store = load_store(store_path)
    store.setdefault("track_id", track_id)
    store.setdefault("records", [])
    store["records"].append(
        {
            "logged_at": pass_payload.get("generated_at"),
            "verdict_counts": pass_payload.get("verdict_counts"),
            "by_algo_action": pass_payload.get("by_algo_action"),
            "cards": pass_payload.get("cards") or [],
        }
    )
    store["last_pass"] = {
        "logged_at": pass_payload.get("generated_at"),
        "card_count": pass_payload.get("card_count"),
        "verdict_counts": pass_payload.get("verdict_counts"),
    }
    store["updated_at"] = _utcnow()
    save_store(store_path, store)

    review = build_review(pass_payload, track_id=track_id)
    (output_dir / REVIEW_FILENAME).write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")
    pass_payload["review"] = review
    return pass_payload


def summarize_learning_tracks_llm_agree_veto(base_dir: Path) -> dict[str, Any]:
    """Roll up per-track agree/veto reviews under the paper-automation root."""
    from value_investor.paper_automation import learning_track_dirs

    tracks: dict[str, Any] = {}
    dirs = learning_track_dirs(base_dir)
    for track_id, track_dir in dirs.items():
        review_path = track_dir / REVIEW_FILENAME
        if review_path.exists():
            try:
                tracks[track_id] = json.loads(review_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                tracks[track_id] = {"track_id": track_id, "error": "invalid_json"}
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utcnow(),
        "observe_only": True,
        "influences_live": False,
        "learning_question": LEARNING_QUESTION,
        "principle": PRINCIPLE,
        "tracks": tracks,
        "note": (
            "Observe-only rollup of algo→agree/veto shadow cards. "
            "Do not treat veto counts as live sell authority."
        ),
    }


def attach_shadow_cards_to_decision_packs(
    reports: list[dict[str, Any]],
    cards: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Embed observe-only agree/veto cards onto matching report decision packs."""
    by_ticker: dict[str, list[dict[str, Any]]] = {}
    for card in cards:
        if not isinstance(card, dict):
            continue
        ticker = str(card.get("ticker") or "").strip()
        if not ticker:
            continue
        # Strip any live-influence attempt before pack attach.
        safe = dict(card)
        safe["influences_live"] = False
        safe["observe_only"] = True
        by_ticker.setdefault(ticker, []).append(safe)
    for report in reports:
        if not isinstance(report, dict):
            continue
        ticker = str(report.get("ticker") or "").strip()
        pack = report.get("decision_pack")
        if not isinstance(pack, dict):
            continue
        matched = by_ticker.get(ticker) or []
        if matched:
            pack[PASS_KEY] = {
                "observe_only": True,
                "influences_live": False,
                "cards": matched,
            }
    return reports
