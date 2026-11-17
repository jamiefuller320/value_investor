"""Observe-only L694 memo-ranking shadow. No spend and no live influence."""

from __future__ import annotations

import inspect
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from value_investor.ops_monitor import (
    check_strategy_book_memo_ranking_shadow,
    collect_ops_findings,
)
from value_investor.strategy_book_memo_ranking_shadow import (
    OBSERVE_CEILING_MEMOS,
    OBSERVE_CEILING_REVIEW_ON,
    OBSERVE_CEILING_USD,
    REGISTERED_MEMO_RAISE_MEMOS,
    REGISTERED_MEMO_RAISE_USD,
    RULE_DOC,
    RULE_ID,
    TITLE_COST,
    TITLE_GAPS,
    TITLE_MISSING,
    TITLE_REFRESHED,
    TITLE_STALE,
    TITLE_UNREADABLE,
    MemoFacts,
    collect_candidates,
    compare_outcomes,
    estimate_cost,
    findings_from_store,
    plan_observe_memos,
    rank_input_gaps,
    read_rule_text,
    request_observe_memos,
    rule_text_in_force,
    run_shadow,
    score_candidate,
)

ROOT = Path(__file__).resolve().parents[1]


def _facts(**overrides) -> MemoFacts:
    base = MemoFacts(
        verdict="accumulate",
        risk_level="low",
        risk_tags=["leverage"],
        confidence=0.8,
        memo_at="2026-11-16T16:00:00+00:00",
        filing_bodies_at="2026-11-15T12:00:00+00:00",
        filing_key_bodies=True,
        filing_source="docs/data/research/AAA.L/sources/filings/filings_index.json",
        fcf_as_of="2026-11-15",
        fcf_bound=True,
        fcf_source="strategy_book_gate_log",
        adjusted_signal="buy",
        overlay_source="docs/data/research/AAA.L/research.json",
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def _candidate(**overrides) -> dict:
    row = {
        "market": "ftse350",
        "ticker": "AAA.L",
        "session": "2026-11-16",
        "role": "primary",
        "disposition": "filled",
        "gate": None,
        "fill_session": "2026-11-17",
        "exit_session": None,
        "fair_cost_return": None,
        "adjusted_signal": "buy",
    }
    row.update(overrides)
    return row


def test_readout_rule_is_in_the_observe_doc() -> None:
    text = (ROOT / RULE_DOC).read_text(encoding="utf-8")
    assert rule_text_in_force(text)
    assert RULE_ID in text
    assert "2026-11-17" in text
    assert "2027-05-16" in text
    assert "2027-11-16" in text
    assert "1.5 percentage points" in text


def test_complete_evidence_scores_and_fail_closes_live_influence() -> None:
    card = score_candidate(_candidate(), _facts())
    assert card["score"] == 3.2
    assert card["score_status"] == "scored"
    assert "verdict:accumulate" in card["reasons"]
    assert "risk:low" in card["reasons"]
    assert "risk_tag:leverage" in card["reasons"]
    kinds = {item["kind"] for item in card["evidence"]}
    assert {"filing", "fcf", "overlay", "memo"} <= kinds
    assert any("bodies_at" in item["detail"] for item in card["evidence"])
    assert card["gaps"] == []
    assert card["influences_live"] is False
    assert card["observe_only"] is True
    assert card["live_influence_authorized"] is False
    assert card["stake_units"] == 100


def test_missing_or_stale_inputs_do_not_score() -> None:
    missing = score_candidate(_candidate(), _facts(filing_key_bodies=False, filing_bodies_at=None))
    assert missing["score"] is None
    assert missing["reasons"] == []
    assert missing["evidence"] == []
    assert missing["no_score_reason"] == "missing_evidence"
    assert "key_filing_bodies" in missing["gaps"]
    assert missing["live_influence_authorized"] is False

    stale = score_candidate(
        _candidate(),
        _facts(filing_bodies_at="2026-11-17T00:00:00+00:00"),
    )
    assert stale["score"] is None
    assert stale["gap_detail"]["key_filing_bodies"] == "stale"
    assert stale["no_score_reason"] == "stale_inputs"

    old_memo = score_candidate(
        _candidate(),
        _facts(memo_at="2026-10-01T16:00:00+00:00"),
    )
    assert old_memo["score"] is None
    assert old_memo["gap_detail"]["memo_recent"] == "stale"

    prose = score_candidate(_candidate(), _facts(verdict="the business looks fine in prose"))
    assert prose["score"] is None
    assert prose["no_score_reason"] == "unstructured_memo"


def test_candidates_cover_fills_slot_skips_and_other_markets() -> None:
    events = [
        {
            "kind": "filled",
            "market": "ftse350",
            "ticker": f"T{index:02d}",
            "session": "2026-11-16",
            "fill_session": "2026-11-17",
            "column": "primary",
        }
        for index in range(21)
    ]
    events.append(
        {
            "kind": "filled",
            "market": "aim",
            "ticker": "CAML.L",
            "session": "2026-11-16",
            "fill_session": "2026-11-17",
            "column": "decline_rejected_shadow",
        }
    )
    events.append(
        {
            "kind": "memo_not_ready",
            "market": "ftse_mib",
            "ticker": "LTMC.MI",
            "session": "2026-11-16",
            "column": "buy_on_signal",
        }
    )
    roster = [
        {
            "market": "asx200",
            "ticker": "XYZ.AX",
            "session": "2026-11-16",
            "price_rule": True,
            "outcome": "gate",
            "decline": "declining",
            "sector": "sound",
            "adjusted_signal": "buy",
        },
        {
            "market": "sp500",
            "ticker": "NO.PE",
            "session": "2026-11-16",
            "price_rule": False,
            "outcome": "gate",
            "decline": "declining",
            "sector": "sound",
        },
    ]
    rows = collect_candidates(events, [], roster, slot_count=20)
    dispositions = {row["disposition"] for row in rows}
    assert dispositions == {"filled", "skipped_no_slot", "gate_rejected"}
    assert sum(1 for row in rows if row["disposition"] == "filled") == 20
    assert sum(1 for row in rows if row["disposition"] == "skipped_no_slot") == 1
    skipped = next(row for row in rows if row["disposition"] == "skipped_no_slot")
    assert skipped["ticker"] == "T20"
    gates = [row for row in rows if row["disposition"] == "gate_rejected"]
    assert {row["market"] for row in gates} == {"aim", "asx200"}
    assert all(row["ticker"] != "LTMC.MI" for row in rows)
    assert all(row["ticker"] != "NO.PE" for row in rows)
    markets = {row["market"] for row in rows if row["disposition"] == "filled"}
    signal_only = {row["market"] for row in rows} - markets
    assert "aim" in signal_only and "asx200" in signal_only


def test_input_gaps_rank_the_cite_that_unlocks_the_most() -> None:
    cards = [
        {"gaps": ["key_filing_bodies"], "no_score_reason": "missing_evidence"},
        {"gaps": ["key_filing_bodies"], "no_score_reason": "missing_evidence"},
        {"gaps": ["key_filing_bodies"], "no_score_reason": "missing_evidence"},
        {"gaps": ["fcf_basis_bound"], "no_score_reason": "missing_evidence"},
        {
            "gaps": ["overlay_bound", "memo_recent"],
            "no_score_reason": "missing_evidence",
        },
    ]
    ranked = rank_input_gaps(cards)
    assert ranked["p1_only"] is True
    assert ranked["ranked_sources"][0]["source"] == "key_filing_bodies"
    assert ranked["ranked_sources"][0]["would_unlock"] == 3
    fcf = next(row for row in ranked["ranked_sources"] if row["source"] == "fcf_basis_bound")
    assert fcf["would_unlock"] == 1
    overlay = next(row for row in ranked["ranked_sources"] if row["source"] == "overlay_bound")
    assert overlay["would_unlock"] == 0
    assert overlay["blocked"] == 1
    assert ranked["auto_fixable"] is False


def test_full_width_cost_proposes_sampling_without_spend() -> None:
    assert OBSERVE_CEILING_USD == 80.0
    assert OBSERVE_CEILING_MEMOS == 200
    assert OBSERVE_CEILING_REVIEW_ON == "2026-11-30"
    assert REGISTERED_MEMO_RAISE_USD == 40.0
    assert REGISTERED_MEMO_RAISE_MEMOS == 100

    # 30 names is $60 a weekday week: over the old $40 cap, inside the ceiling.
    relaxed = estimate_cost(
        [{"session": "2026-11-16", "disposition": "gate_rejected"} for _ in range(30)]
    )
    assert relaxed["latest_session_usd"] == 12.0
    assert relaxed["weekday_week_usd"] == 60.0
    assert relaxed["over_budget"] is False
    assert relaxed["sampling"] is None
    assert relaxed["weekly_budget_usd"] == 80.0

    cards = [{"session": "2026-11-16", "disposition": "gate_rejected"} for _ in range(50)]
    cost = estimate_cost(cards)
    assert cost["usd_per_candidate_per_day"] == 0.40
    assert cost["latest_session_usd"] == 20.0
    assert cost["weekday_week_usd"] == 100.0
    assert cost["over_budget"] is True
    assert cost["sampling"]["id"] == "l694-memo-sample-v1"
    assert cost["sampling"]["weekly_cap_usd"] == 80.0
    assert cost["sampling"]["relaxed_from_usd"] == 40.0
    assert cost["sampling"]["review_on"] == "2026-11-30"
    assert cost["sampling"]["turns_spend_on"] is False
    assert cost["sampling"]["priority"] == ["filled", "skipped_no_slot", "gate_rejected"]
    assert cost["spend_enabled"] is False
    assert cost["influences_live"] is False

    inside = estimate_cost([{"session": "2026-11-16"} for _ in range(10)])
    assert inside["over_budget"] is False
    assert inside["sampling"] is None
    assert inside["spend_enabled"] is False


def test_outcomes_are_not_evidence_without_the_rule_or_the_minimum() -> None:
    thick = _closed_pool()
    blocked = compare_outcomes(thick, rule_text="")
    assert blocked["status"] == "rule_not_in_force"
    assert blocked["comparison"] is None
    assert blocked["counts_as_evidence"] is False

    early = compare_outcomes(thick[:10], rule_text=read_rule_text(ROOT))
    assert early["status"] == "awaiting_closed_outcomes"
    assert early["comparison"] is None
    assert early["counts_as_evidence"] is False

    before = []
    for card in thick:
        shifted = dict(card)
        shifted["session"] = "2026-11-16"
        shifted["fill_session"] = "2026-11-16"
        before.append(shifted)
    prior = compare_outcomes(before, rule_text=read_rule_text(ROOT))
    assert prior["closed_in_window"] == 0
    assert prior["comparison"] is None
    assert prior["counts_as_evidence"] is False


def test_synthetic_pool_can_compare_only_after_the_rule_text() -> None:
    """Arithmetic check on a made-up pool. Not the forward book."""
    result = compare_outcomes(_closed_pool(), rule_text=read_rule_text(ROOT), slot_count=1)
    assert result["rule_in_force"] is True
    assert result["status"] == "compared"
    assert result["counts_as_evidence"] is True
    halves = result["comparison"]["halves"]
    assert halves["a"]["memo_rank_median"] == 0.10
    assert halves["a"]["registered_order_median"] == 0.01
    assert halves["b"]["memo_rank_median"] == 0.10
    assert result["comparison"]["beats_registered_and_random"] is True


def test_run_does_not_score_pre_rule_sessions_or_write_the_book(tmp_path: Path) -> None:
    data = tmp_path / "docs" / "data"
    data.mkdir(parents=True)
    (tmp_path / "docs" / "ops").mkdir(parents=True)
    (tmp_path / RULE_DOC).write_text(read_rule_text(ROOT), encoding="utf-8")
    observe = data / "strategy_book_observe.json"
    observe.write_text(
        json.dumps(
            {
                "influences_live": False,
                "events": [
                    {
                        "kind": "filled",
                        "market": "ftse350",
                        "ticker": "FOUR.L",
                        "session": "2026-11-12",
                        "fill_session": "2026-11-13",
                        "column": "primary",
                    }
                ],
                "episodes": [],
            }
        ),
        encoding="utf-8",
    )
    sentinel = observe.read_text(encoding="utf-8")
    summary = run_shadow(
        repo_root=tmp_path,
        now=datetime(2026, 11, 16, 22, tzinfo=UTC),
        apply=True,
        facts_for=lambda _candidate: _facts(),
    )
    assert observe.read_text(encoding="utf-8") == sentinel
    assert summary["influences_live"] is False
    assert summary["spend_enabled"] is False
    assert summary["readout_status"] == "awaiting_closed_outcomes"
    assert summary["counts_as_evidence"] is False
    stored = json.loads(
        (data / "strategy_book_memo_ranking_shadow.json").read_text(encoding="utf-8")
    )
    assert stored["influences_live"] is False
    assert stored["readout"]["comparison"] is None
    assert "forward_live" not in stored


def test_ops_monitor_is_observe_only(tmp_path: Path) -> None:
    missing = check_strategy_book_memo_ranking_shadow(
        repo_root=tmp_path, now=datetime(2026, 11, 16, 22, tzinfo=UTC)
    )
    assert missing[0].title == TITLE_MISSING
    assert missing[0].severity == "warn"
    assert missing[0].auto_fixable is False

    data = tmp_path / "docs" / "data"
    data.mkdir(parents=True)
    path = data / "strategy_book_memo_ranking_shadow.json"
    path.write_text("{", encoding="utf-8")
    broken = check_strategy_book_memo_ranking_shadow(repo_root=tmp_path)
    assert broken[0].title == TITLE_UNREADABLE
    assert broken[0].auto_fixable is False

    path.write_text(
        json.dumps(
            {
                "generated_at": "2026-11-01T00:00:00+00:00",
                "counts": {},
                "cost": {},
                "input_gaps": {},
            }
        ),
        encoding="utf-8",
    )
    stale = findings_from_store(
        json.loads(path.read_text(encoding="utf-8")),
        now=datetime(2026, 11, 16, 22, tzinfo=UTC),
    )
    assert stale[0]["title"] == TITLE_STALE
    assert stale[0]["auto_fixable"] is False

    fresh = {
        "generated_at": "2026-11-16T21:40:00+00:00",
        "influences_live": False,
        "counts": {
            "candidates": 4,
            "filled": 1,
            "skipped_no_slot": 1,
            "gate_rejected": 2,
            "scored": 0,
        },
        "markets": {"signal_markets_without_buys": ["aim"]},
        "cost": {
            "usd_per_candidate_per_day": 0.4,
            "weekday_week_usd": 60.0,
            "sampling": {"id": "l694-memo-sample-v1"},
        },
        "input_gaps": {
            "ranked_sources": [
                {"rank": 1, "source": "key_filing_bodies", "would_unlock": 2},
            ]
        },
        "readout": {"status": "awaiting_closed_outcomes", "counts_as_evidence": False},
    }
    rows = findings_from_store(fresh, now=datetime(2026, 11, 16, 22, tzinfo=UTC))
    titles = [row["title"] for row in rows]
    assert titles == [TITLE_REFRESHED, TITLE_COST, TITLE_GAPS]
    assert all(row["auto_fixable"] is False for row in rows)
    assert all(row["severity"] == "info" for row in rows)
    assert "does not turn on live capital" in rows[1]["summary"]
    assert "influences_live stays false" in rows[1]["summary"]
    assert "$80" in rows[1]["summary"]
    assert "No ingest" in rows[2]["summary"]
    assert "check_strategy_book_memo_ranking_shadow" in inspect.getsource(collect_ops_findings)


def _closed_pool() -> list[dict]:
    """48 closed names in each half would be more than the minimum; 24 days × 2."""
    rows: list[dict] = []
    for half_start, days in ((date(2026, 11, 17), 24), (date(2027, 5, 17), 24)):
        for offset in range(days):
            session = (half_start + timedelta(days=offset)).isoformat()
            fill = (half_start + timedelta(days=offset + 1)).isoformat()
            exit_on = (half_start + timedelta(days=offset + 2)).isoformat()
            for ticker, score, fair in (("AAA", 1.0, 0.01), ("ZZZ", 3.0, 0.10)):
                rows.append(
                    {
                        "market": "ftse350",
                        "ticker": ticker,
                        "session": session,
                        "role": "primary",
                        "disposition": "filled",
                        "gate": None,
                        "fill_session": fill,
                        "exit_session": exit_on,
                        "fair_cost_return": fair,
                        "score": score,
                        "score_status": "scored",
                    }
                )
    return rows


def test_observe_memo_plan_reuses_fresh_memos_and_keeps_the_raise() -> None:
    now = datetime(2026, 11, 17, 1, tzinfo=UTC)
    fresh = (now - timedelta(days=3)).isoformat()
    stale = (now - timedelta(days=40)).isoformat()
    names = [
        {"market": "ftse350", "ticker": "B.L", "disposition": "gate_rejected", "memo_at": stale},
        {"market": "ftse350", "ticker": "A.L", "disposition": "filled", "memo_at": None},
        {"market": "sp500", "ticker": "ZZ", "disposition": "filled", "memo_at": fresh},
        {"market": "ftse350", "ticker": "A.L", "disposition": "skipped_no_slot", "memo_at": None},
    ]
    plan = plan_observe_memos(
        names,
        now=now,
        spent_this_week_usd=79.6,
        full_width_over_budget=True,
    )
    assert [row["ticker"] for row in plan["selected"]] == ["A.L"]
    assert plan["selected"][0]["disposition"] == "filled"
    assert plan["cap"] == 1
    assert plan["sampling_applied"] is True
    assert [row["ticker"] for row in plan["held_for_budget"]] == ["B.L"]
    assert plan["reused"][0]["ticker"] == "ZZ"

    inside = plan_observe_memos(
        names,
        now=now,
        spent_this_week_usd=39.6,
        full_width_over_budget=False,
    )
    assert [row["ticker"] for row in inside["selected"]] == ["A.L", "B.L"]
    assert inside["held_for_budget"] == []
    assert inside["sampling_applied"] is False


def test_observe_memo_request_records_spend_and_stays_observe_only(tmp_path: Path) -> None:
    (tmp_path / "docs" / "data").mkdir(parents=True)
    calls: list[str] = []
    spent: list[float] = []

    def runner(**kwargs):
        calls.append(kwargs["ticker"])
        return {
            "verdict": "accumulate",
            "finished_at": "2026-11-17T01:00:00+00:00",
            "written_paths": [
                "docs/data/research/NEW.L/research.json",
                "docs/data/research/NEW.L/sources/news.json",
            ],
        }

    result = request_observe_memos(
        [
            {
                "market": "ftse350",
                "ticker": "NEW.L",
                "disposition": "filled",
                "session": "2026-11-16",
                "memo_at": None,
            }
        ],
        repo_root=tmp_path,
        now=datetime(2026, 11, 17, 1, tzinfo=UTC),
        spent_this_week_usd=0.0,
        full_width_over_budget=False,
        apply=True,
        runner=runner,
        budget_status=lambda: {"remaining_weekly_ops_usd": 50.0},
        record_spend=spent.append,
    )
    assert calls == ["NEW.L"]
    assert spent == [0.4]
    assert result["estimated_spend_usd"] == 0.4
    assert result["influences_live"] is False
    assert result["spend_enabled"] is False
    assert result["names"][0]["action"] == "requested"
    assert result["written_paths"] == ["docs/data/research/NEW.L/research.json"]
    assert result["spend_enabled"] is False
    log = (tmp_path / "docs" / "data" / "strategy_book_memo_ranking_shadow_memos.jsonl").read_text(
        encoding="utf-8"
    )
    assert "influences_live" in log
    assert "false" in log
