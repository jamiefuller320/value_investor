"""Structured buy/sell decision reasons for post-sale review (Package M)."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.post_sale_decision_reasons import (
    UNKNOWN_CODE,
    UNKNOWN_LABEL,
    bind_decision_reasons,
    format_decision_reasons_for_prompt,
    load_control_trade_index,
    load_sealed_episode_indexes,
)
from value_investor.post_sale_review import build_post_sale_review_queue
from value_investor.post_sale_review_opinion import (
    build_contextual_reply_text,
    build_initial_opinion,
    build_llm_reply_prompt,
)
from value_investor.sealed_lifecycle import assign_sealed_phase, slim_lifecycle_episode


def test_n200_model_identity_binds_without_episode_join():
    item = {
        "book_id": "n200",
        "model_id": "n200",
        "book_tag": "N200",
        "ticker": "AAA.L",
        "entry_at": "2026-10-01T10:00:00+00:00",
        "exit_at": "2026-10-20T10:00:00+00:00",
    }
    bind_decision_reasons(item, sealed_indexes={}, control_trades={})
    assert item["buy_decision"]["join_ok"] is True
    assert item["buy_decision"]["code"] == "enter_buy_tier"
    assert item["sell_decision"]["join_ok"] is True
    assert item["sell_decision"]["code"] == "leave_buy_tier"
    assert "buy-tier" in item["sell_reason"].lower()


def test_observe_exit_reason_join_and_fail_closed():
    indexes = {
        "n206": {
            "SHL.AX|2026-10-16|2026-10-23": {
                "ticker": "SHL.AX",
                "entry_run_at": "2026-10-16T06:52:34+00:00",
                "exit_run_at": "2026-10-23T06:52:47+00:00",
                "exit_reason": "identity_break_ey_band",
                "entry_detail": {
                    "in_ey_top30_local": True,
                    "financial_health_pass": True,
                    "require_momentum": False,
                },
            }
        }
    }
    item = {
        "book_id": "n206",
        "model_id": "n206",
        "ticker": "SHL.AX",
        "entry_at": "2026-10-16T06:52:34+00:00",
        "exit_at": "2026-10-23T06:52:47+00:00",
    }
    bind_decision_reasons(item, sealed_indexes=indexes, control_trades={})
    assert item["sell_decision"]["code"] == "identity_break_ey_band"
    assert item["sell_decision"]["join_ok"] is True
    assert "EY" in item["sell_decision"]["label"]
    assert item["buy_decision"]["join_ok"] is True
    assert item["buy_decision"]["code"] == "filters_newly_clear"

    orphan = {
        "book_id": "n206",
        "model_id": "n206",
        "ticker": "ZZZ.AX",
        "entry_at": "2026-01-01T00:00:00+00:00",
        "exit_at": "2026-02-01T00:00:00+00:00",
    }
    bind_decision_reasons(orphan, sealed_indexes=indexes, control_trades={})
    # Entry is deterministic model identity; sell must stay fail-closed without exit_reason.
    assert orphan["buy_decision"]["join_ok"] is True
    assert orphan["buy_decision"]["code"] == "filters_newly_clear"
    assert orphan["sell_decision"]["join_ok"] is False
    assert orphan["sell_decision"]["code"] == UNKNOWN_CODE
    assert orphan["sell_decision"]["label"] == UNKNOWN_LABEL

    # Slim lifecycle row without entry_detail must not invent sell; entry may use identity.
    slim_only = {
        "book_id": "n206",
        "model_id": "n206",
        "ticker": "SLIM.L",
        "entry_at": "2026-03-01T00:00:00+00:00",
        "exit_at": "2026-04-01T00:00:00+00:00",
    }
    bind_decision_reasons(
        slim_only,
        sealed_indexes={
            "n206": {
                "SLIM.L|2026-03-01|2026-04-01": {
                    "ticker": "SLIM.L",
                    "entry_run_at": "2026-03-01T00:00:00+00:00",
                    "exit_run_at": "2026-04-01T00:00:00+00:00",
                }
            }
        },
        control_trades={},
    )
    assert slim_only["sell_decision"]["join_ok"] is False
    assert slim_only["buy_decision"]["source"].startswith("model_identity.")


def test_control_rebalance_note_join(tmp_path: Path):
    log_dir = tmp_path / "paper_automation" / "buy_tier_level"
    log_dir.mkdir(parents=True)
    (log_dir / "rebalance_log.json").write_text(
        json.dumps(
            [
                {
                    "logged_at": "2026-10-18T09:00:00+00:00",
                    "trades": [
                        {
                            "ticker": "BBB.L",
                            "side": "buy",
                            "acted_at": "2026-10-05T09:00:00+00:00",
                            "note": "Automated buy",
                        },
                        {
                            "ticker": "BBB.L",
                            "side": "sell",
                            "acted_at": "2026-10-18T09:00:00+00:00",
                            "note": "Automated exit — left target set",
                            "position_closed": True,
                        },
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )
    trades = load_control_trade_index(tmp_path)
    item = {
        "book_id": "ftse_control",
        "model_id": "buy_tier_level",
        "ticker": "BBB.L",
        "entry_at": "2026-10-05T09:00:00+00:00",
        "exit_at": "2026-10-18T09:00:00+00:00",
    }
    bind_decision_reasons(item, sealed_indexes={}, control_trades=trades)
    assert item["sell_decision"]["code"] == "left_target_set"
    assert item["sell_decision"]["join_ok"] is True
    assert item["buy_decision"]["code"] == "enter_target_set"
    assert item["buy_decision"]["join_ok"] is True


def test_slim_and_chip_preserve_exit_reason():
    from datetime import UTC, datetime

    slim = slim_lifecycle_episode(
        {
            "ticker": "CCC.L",
            "entry_run_at": "2026-10-01T00:00:00+00:00",
            "exit_run_at": "2026-10-10T00:00:00+00:00",
            "status": "closed",
            "return_pct": -0.05,
            "exit_reason": "hold_trading_days",
            "entry_reason": "filters_newly_clear",
            "entry_detail": {
                "in_ey_top30_local": True,
                "financial_health_pass": True,
                "require_momentum": True,
                "noise_field": "drop-me",
            },
        }
    )
    assert slim is not None
    assert slim["exit_reason"] == "hold_trading_days"
    assert slim["entry_reason"] == "filters_newly_clear"
    assert "noise_field" not in slim["entry_detail"]
    chip = assign_sealed_phase(slim, now=datetime(2026, 10, 12, tzinfo=UTC))
    assert chip is not None
    assert chip["exit_reason"] == "hold_trading_days"
    assert chip["entry_reason"] == "filters_newly_clear"


def test_opinion_and_reply_cite_reasons():
    item = {
        "book_tag": "N206",
        "book_id": "n206",
        "model_id": "n206",
        "ticker": "SHL.AX",
        "hold_days": 7,
        "return_pct": 1.37,
        "exit_kind": "just_sold",
        "basis_label": "fair_cost_episode",
        "entry_at": "2026-10-16T06:52:34+00:00",
        "exit_at": "2026-10-23T06:52:47+00:00",
        "buy_decision": {
            "code": "filters_newly_clear",
            "label": "Filters newly cleared (entry): EY top 30%, FH pass, no mom gate",
            "source": "observe.entry",
            "join_ok": True,
            "structured": {},
        },
        "sell_decision": {
            "code": "identity_break_ey_band",
            "label": "Left EY top band (identity break)",
            "source": "observe.exit_reason",
            "join_ok": True,
            "structured": {"raw": "identity_break_ey_band"},
        },
    }
    opinion = build_initial_opinion(item)
    assert "Bought because:" in opinion["llm_opinion"]
    assert "Sold because:" in opinion["llm_opinion"]
    assert "identity" in opinion["llm_opinion"].lower() or "EY" in opinion["llm_opinion"]
    reply = build_contextual_reply_text(owner_comment="premature sell?", item=item)
    assert "Sold because:" in reply or "sold because:" in reply.lower()
    assert "identity_break_ey_band" in reply
    prompt = build_llm_reply_prompt(owner_comment="premature?", item=item)
    assert "decision_reasons" in prompt
    assert "identity_break_ey_band" in prompt
    packed = format_decision_reasons_for_prompt(item)
    assert packed["sell"]["join_ok"] is True


def test_queue_surfaces_reasons_on_n200(tmp_path: Path):
    sealed = {
        "models": [
            {
                "model_id": "n200",
                "label": "N200",
                "registration_id": "strand-b-plain-value-tech-timing-v0",
                "columns": {
                    "just_sold": {
                        "count": 1,
                        "chips": [
                            {
                                "ticker": "AAA.L",
                                "phase": "just_sold",
                                "status": "closed",
                                "entry_run_at": "2026-10-01T10:00:00+00:00",
                                "exit_run_at": "2026-10-20T10:00:00+00:00",
                                "return_pct": -0.12,
                                "return_basis": "fair_cost_episode",
                                "days_in_phase": 3,
                            }
                        ],
                    },
                    "post_sale": {"count": 0, "chips": []},
                },
            }
        ]
    }
    payload = build_post_sale_review_queue(
        data_dir=tmp_path,
        sealed=sealed,
        board={"markets": []},
        labels={"actioned_review_ids": [], "events": [], "active_replies": []},
    )
    row = next(r for r in payload["active"] if r["ticker"] == "AAA.L")
    assert row["buy_decision"]["code"] == "enter_buy_tier"
    assert row["sell_decision"]["code"] == "leave_buy_tier"
    assert "Bought because:" in row["framing"]
    assert "Sold because:" in row["framing"]
    assert "leave" in row["llm_opinion"].lower() or "buy-tier" in row["llm_opinion"].lower()


def test_load_indexes_tolerates_missing_stores(tmp_path: Path):
    assert load_sealed_episode_indexes(tmp_path)["n200"] == {}
    assert load_control_trade_index(tmp_path) == {}
