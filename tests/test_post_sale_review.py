"""Post-sale review queue + Accept/Comment reply stub (Package M)."""

from __future__ import annotations

from pathlib import Path

from value_investor.post_sale_review import (
    CONTROL_BOOK_ID,
    build_post_sale_review_queue,
    episode_key,
    ops_findings_from_queue,
    refresh_post_sale_review_queue,
    review_fingerprint,
    sort_queue_items,
    wider_tf_window,
)
from value_investor.post_sale_review_actions import run_post_sale_review_action
from value_investor.post_sale_review_labels import (
    comments_awaiting_reply,
    load_post_sale_review_labels,
)
from value_investor.post_sale_review_opinion import (
    OPINION_SOURCE_DETERMINISTIC,
    build_initial_opinion,
    generate_factory_reply,
)


def _sealed_fixture() -> dict:
    return {
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
                    "post_sale": {
                        "count": 1,
                        "chips": [
                            {
                                "ticker": "OLD.L",
                                "phase": "post_sale",
                                "status": "closed",
                                "entry_run_at": "2025-01-01T10:00:00+00:00",
                                "exit_run_at": "2025-06-01T10:00:00+00:00",
                                "return_pct": 0.05,
                                "return_basis": "fair_cost_episode",
                                "days_in_phase": 200,
                            }
                        ],
                    },
                },
            }
        ]
    }


def _board_fixture() -> dict:
    return {
        "markets": [
            {
                "market_id": "ftse350",
                "label": "FTSE 350",
                "is_live": True,
                "tracks": [
                    {
                        "track_id": "buy_tier_level",
                        "track_label": "Buy-tier level",
                        "position_columns": {
                            "just_sold": {
                                "count": 1,
                                "shown": [
                                    {
                                        "ticker": "BBB.L",
                                        "name": "Bee Bee",
                                        "opened_at": "2026-10-05T09:00:00+00:00",
                                        "sold_at": "2026-10-18T09:00:00+00:00",
                                        "realized_exit_pnl_pct": -0.08,
                                        "avg_cost": 100.0,
                                        "exit_price": 92.0,
                                        "days_in_column": 5,
                                    }
                                ],
                            },
                            "post_sale": {"count": 0, "shown": []},
                        },
                    }
                ],
            }
        ]
    }


def test_review_fingerprint_stable():
    a = review_fingerprint(
        book_id="n200",
        ticker="aaa.l",
        entry_at="2026-10-01",
        exit_at="2026-10-20",
    )
    b = review_fingerprint(
        book_id="n200",
        ticker="AAA.L",
        entry_at="2026-10-01",
        exit_at="2026-10-20",
    )
    assert a == b
    assert len(a) == 20


def test_episode_key_collapses_same_day_entry_jitter():
    """Near-dup chips with second-level entry jitter share one episode_key."""
    a = episode_key(
        book_id="n206",
        ticker="PYPL",
        entry_at="2026-07-18T12:36:13+00:00",
        exit_at="2026-10-16T06:52:34+00:00",
    )
    b = episode_key(
        book_id="n206",
        ticker="pypl",
        entry_at="2026-07-18T12:36:32+00:00",
        exit_at="2026-10-16T06:52:34+00:00",
    )
    assert a == b
    # Distinct entry *days* stay distinct (real multi-episode).
    c = episode_key(
        book_id="n206",
        ticker="PYPL",
        entry_at="2026-07-19T12:36:13+00:00",
        exit_at="2026-10-16T06:52:34+00:00",
    )
    assert c != a
    # Cross-book same ticker is intentional — different episode_key.
    other_book = episode_key(
        book_id="n201",
        ticker="PYPL",
        entry_at="2026-07-18T12:36:13+00:00",
        exit_at="2026-10-16T06:52:34+00:00",
    )
    assert other_book != a


def test_build_queue_dedupes_same_day_near_dupes_keeps_cross_book(tmp_path: Path):
    sealed = {
        "models": [
            {
                "model_id": "n206",
                "label": "N206",
                "registration_id": "n206-reg",
                "columns": {
                    "just_sold": {
                        "count": 2,
                        "chips": [
                            {
                                "ticker": "PYPL",
                                "phase": "just_sold",
                                "status": "closed",
                                "entry_run_at": "2026-07-18T12:36:13+00:00",
                                "exit_run_at": "2026-10-16T06:52:34+00:00",
                                "return_pct": 0.007,
                                "return_basis": "fair_cost_episode",
                                "days_in_phase": 3,
                            },
                            {
                                "ticker": "PYPL",
                                "phase": "just_sold",
                                "status": "closed",
                                "entry_run_at": "2026-07-18T12:36:32+00:00",
                                "exit_run_at": "2026-10-16T06:52:34+00:00",
                                "return_pct": -0.025,
                                "return_basis": "fair_cost_episode",
                                "days_in_phase": 3,
                            },
                        ],
                    },
                    "post_sale": {"count": 0, "chips": []},
                },
            },
            {
                "model_id": "n201",
                "label": "N201",
                "registration_id": "n201-reg",
                "columns": {
                    "just_sold": {
                        "count": 1,
                        "chips": [
                            {
                                "ticker": "PYPL",
                                "phase": "just_sold",
                                "status": "closed",
                                "entry_run_at": "2026-07-18T12:36:13+00:00",
                                "exit_run_at": "2026-10-16T06:52:34+00:00",
                                "return_pct": -0.025,
                                "return_basis": "fair_cost_episode",
                                "days_in_phase": 3,
                            }
                        ],
                    },
                    "post_sale": {"count": 0, "chips": []},
                },
            },
        ]
    }
    payload = build_post_sale_review_queue(
        data_dir=tmp_path,
        sealed=sealed,
        board={"markets": []},
        labels={"actioned_review_ids": [], "events": [], "active_replies": []},
    )
    pypl = [row for row in payload["active"] if row["ticker"] == "PYPL"]
    assert len(pypl) == 2  # one per book
    books = {row["book_id"] for row in pypl}
    assert books == {"n206", "n201"}
    n206 = next(row for row in pypl if row["book_id"] == "n206")
    # Worse return kept when collapsing same-day jitter.
    assert n206["return_pct"] == -2.5
    assert "episode_key" in n206
    assert payload["duplicate_policy"]["cross_book"].startswith("intentional")
    assert payload["sort_default"] == "interesting"
    assert any(row["id"] == "interesting" for row in payload["sort_options"])
    assert any(row["id"] == "exit_at" for row in payload["sort_options"])
    assert any(row["id"] == "ticker" for row in payload["sort_options"])


def test_sort_queue_items_date_and_stock():
    rows = [
        {
            "ticker": "BBB.L",
            "name": "Bee",
            "exit_at": "2026-10-10T00:00:00+00:00",
            "book_tag": "N200",
            "return_pct": -1.0,
            "tag": "new",
        },
        {
            "ticker": "AAA.L",
            "name": "Aye",
            "exit_at": "2026-10-20T00:00:00+00:00",
            "book_tag": "N206",
            "return_pct": -5.0,
            "tag": "new",
        },
    ]
    by_date = sort_queue_items(rows, sort_by="exit_at", descending=True)
    assert [r["ticker"] for r in by_date] == ["AAA.L", "BBB.L"]
    by_stock = sort_queue_items(rows, sort_by="ticker", descending=False)
    assert [r["ticker"] for r in by_stock] == ["AAA.L", "BBB.L"]


def test_sort_queue_items_interesting_puts_identity_break_first():
    from value_investor.post_sale_decision_reasons import sell_interest_rank

    rows = [
        {
            "ticker": "MECH.L",
            "exit_at": "2026-10-22T00:00:00+00:00",
            "tag": "new",
            "sell_decision": {"code": "hold_trading_days", "label": "Hold horizon"},
        },
        {
            "ticker": "LEAVE.L",
            "exit_at": "2026-10-21T00:00:00+00:00",
            "tag": "new",
            "sell_decision": {"code": "leave_buy_tier", "label": "Left buy-tier"},
        },
        {
            "ticker": "ID.L",
            "exit_at": "2026-10-10T00:00:00+00:00",
            "tag": "new",
            "sell_decision": {
                "code": "identity_break_ey_band",
                "label": "Left EY top band",
            },
        },
        {
            "ticker": "ID2.L",
            "exit_at": "2026-10-20T00:00:00+00:00",
            "tag": "reply",
            "sell_decision": {
                "code": "identity_break_ey_band",
                "label": "Left EY top band",
            },
        },
    ]
    assert sell_interest_rank(rows[0]) == 2
    assert sell_interest_rank(rows[2]) == 0
    ordered = sort_queue_items(rows, sort_by="interesting")
    assert [r["ticker"] for r in ordered] == ["ID2.L", "ID.L", "MECH.L", "LEAVE.L"]


def test_wider_tf_window_pads_episode():
    window = wider_tf_window("2026-10-01T00:00:00+00:00", "2026-10-20T00:00:00+00:00")
    assert window is not None
    assert window["days_before"] == 180
    assert window["days_after"] == 90
    assert window["start"] < "2026-10-01"
    assert window["end"] > "2026-10-20"


def test_build_queue_covers_sealed_and_control(tmp_path: Path):
    payload = build_post_sale_review_queue(
        data_dir=tmp_path,
        sealed=_sealed_fixture(),
        board=_board_fixture(),
        labels={"actioned_review_ids": [], "events": [], "active_replies": []},
    )
    assert payload["influences_live"] is False
    assert payload["package"] == "M"
    tickers = {row["ticker"] for row in payload["active"]}
    assert "AAA.L" in tickers
    assert "BBB.L" in tickers
    # Stale sealed post_sale beyond 84d is excluded from active candidates.
    assert "OLD.L" not in tickers
    books = {row["book_id"] for row in payload["active"]}
    assert "n200" in books
    assert CONTROL_BOOK_ID in books
    sample = next(row for row in payload["active"] if row["ticker"] == "AAA.L")
    assert sample["tag"] == "new"
    assert sample["charts"]["episode"]
    assert sample["charts"]["wider_tf"]
    assert "Outcome" in sample["framing"]
    assert sample["llm_opinion"]
    assert isinstance(sample["learning_points"], list) and sample["learning_points"]
    assert sample["chart_annotations"]["episode"]
    assert sample["chart_annotations"]["wider_tf"]
    assert sample["dialogue"][0]["kind"] == "initial_opinion"
    assert sample["influences_live"] is False


def test_accept_clears_active_and_comment_spawns_reply(tmp_path: Path):
    data_dir = tmp_path
    (data_dir / "sealed_lifecycle.json").write_text("{}", encoding="utf-8")
    queue = build_post_sale_review_queue(
        data_dir=data_dir,
        sealed=_sealed_fixture(),
        board=_board_fixture(),
    )
    item = next(row for row in queue["active"] if row["ticker"] == "AAA.L")
    rid = item["review_id"]

    accept = run_post_sale_review_action(
        data_dir,
        review_id=rid,
        decision="accept",
        tag_at_action="new",
        source="test",
        snapshot=item,
    )
    assert accept["ok"] is True
    assert accept["influences_live"] is False
    refreshed = build_post_sale_review_queue(
        data_dir=data_dir, sealed=_sealed_fixture(), board=_board_fixture()
    )
    assert all(row["review_id"] != rid for row in refreshed["active"])

    control = next(row for row in refreshed["active"] if row["ticker"] == "BBB.L")
    # Force deterministic contextual reply (no live LLM in unit tests).
    from value_investor.post_sale_review_labels import record_comment

    comment_event = record_comment(
        data_dir,
        review_id=control["review_id"],
        text="Missed climbing wider TF",
        tag_at_action="new",
        source="test",
        acted_by="test",
        snapshot=control,
        allow_llm_reply=False,
    )
    reply = comment_event["reply"]
    assert reply["tag"] == "reply"
    assert "Acknowledged owner Comment" in reply["reply_text"]
    assert "Missed climbing wider TF" in reply["reply_text"]
    assert reply["dialogue"][-1]["kind"] == "reply"
    assert reply["dialogue"][-2]["kind"] == "comment"
    assert comment_event.get("reply_review_id")

    after = build_post_sale_review_queue(
        data_dir=data_dir, sealed=_sealed_fixture(), board=_board_fixture()
    )
    assert all(row["review_id"] != control["review_id"] for row in after["active"])
    # Commented episode must not reappear — including as a reply:* card.
    assert all(row.get("tag") != "reply" for row in after["active"])
    assert after["reply_count"] == 0
    assert reply.get("owner_comment") == "Missed climbing wider TF"
    assert reply.get("llm_opinion")
    assert len(reply.get("dialogue") or []) >= 3

    labels = load_post_sale_review_labels(data_dir)
    assert comments_awaiting_reply(labels) == []
    assert labels.get("active_replies") == []
    kinds = [row["kind"] for row in labels["events"]]
    assert kinds.count("accept") == 1
    assert kinds.count("comment") == 1
    assert kinds.count("reply") == 1
    # Factory reply is durable history, not an active queue card.
    assert any(row.get("kind") == "reply" for row in labels["events"])


def test_ops_findings_and_refresh(tmp_path: Path):
    sealed_path = tmp_path / "sealed_lifecycle.json"
    board_path = tmp_path / "lifecycle_board.json"
    import json

    sealed_path.write_text(json.dumps(_sealed_fixture()), encoding="utf-8")
    board_path.write_text(json.dumps(_board_fixture()), encoding="utf-8")
    store = tmp_path / "post_sale_review_queue.json"
    payload = refresh_post_sale_review_queue(data_dir=tmp_path, store_path=store, persist=True)
    assert store.is_file()
    assert payload["active_count"] >= 2
    findings = ops_findings_from_queue(payload)
    titles = {row["title"] for row in findings}
    assert "Post-sale review queue (observe)" in titles
    assert all(row["auto_fixable"] is False for row in findings)
    assert payload.get("dialogue", {}).get("influences_live") is False


def test_initial_opinion_and_llm_reply_fallback():
    item = {
        "book_tag": "N206",
        "ticker": "SHL.AX",
        "hold_days": 7,
        "return_pct": 1.37,
        "exit_kind": "just_sold",
        "basis_label": "fair_cost_episode",
        "entry_at": "2026-10-16T06:52:34+00:00",
        "exit_at": "2026-10-23T06:52:47+00:00",
    }
    opinion = build_initial_opinion(item)
    assert opinion["opinion_source"] == OPINION_SOURCE_DETERMINISTIC
    assert opinion["influences_live"] is False
    assert "SHL.AX" in opinion["llm_opinion"]
    assert opinion["learning_points"]

    def boom(_prompt: str) -> str:
        raise RuntimeError("no llm in unit test")

    reply = generate_factory_reply(
        owner_comment="Looks like bottom of range",
        item=item,
        llm_complete=boom,
        allow_llm=True,
    )
    assert reply["llm_attempted"] is True
    assert reply["llm_ok"] is False
    assert reply["influences_live"] is False
    assert "bottom of range" in reply["text"]

    ok_reply = generate_factory_reply(
        owner_comment="Missed climb",
        item=item,
        llm_complete=lambda _p: '{"reply": "Noted the climb on wider TF. influences_live=false."}',
        allow_llm=True,
    )
    assert ok_reply["reply_kind"] == "llm"
    assert "Noted the climb" in ok_reply["text"]


def test_blank_reply_cards_suppressed_from_active(tmp_path: Path):
    """Legacy ``active_replies`` (blank or usable) must not enter the active queue."""
    labels = {
        "actioned_review_ids": ["parent-ok"],
        "events": [],
        "active_replies": [
            {
                "review_id": "reply:blank",
                "parent_review_id": "parent-ok",
                "tag": "reply",
                "ticker": None,
                "book_tag": None,
                "owner_comment": "noise",
                "reply_text": "stub",
            },
            {
                "review_id": "reply:ok",
                "parent_review_id": "parent-ok",
                "tag": "reply",
                "ticker": "AAA.L",
                "book_tag": "N200",
                "book_id": "n200",
                "exit_at": "2026-10-20T10:00:00+00:00",
                "entry_at": "2026-10-01T10:00:00+00:00",
                "owner_comment": "real",
                "reply_text": "stub",
            },
        ],
    }
    payload = build_post_sale_review_queue(
        data_dir=tmp_path,
        sealed=_sealed_fixture(),
        board=_board_fixture(),
        labels=labels,
    )
    assert all(row.get("tag") != "reply" for row in payload["active"])
    assert "reply:blank" not in {row["review_id"] for row in payload["active"]}
    assert "reply:ok" not in {row["review_id"] for row in payload["active"]}
    assert all(row.get("ticker") not in (None, "", "?") for row in payload["active"])


def test_duplicate_clears_without_reply(tmp_path: Path):
    data_dir = tmp_path
    (data_dir / "sealed_lifecycle.json").write_text("{}", encoding="utf-8")
    queue = build_post_sale_review_queue(
        data_dir=data_dir,
        sealed=_sealed_fixture(),
        board=_board_fixture(),
    )
    item = next(row for row in queue["active"] if row["ticker"] == "AAA.L")
    rid = item["review_id"]
    result = run_post_sale_review_action(
        data_dir,
        review_id=rid,
        decision="duplicate",
        tag_at_action="new",
        source="test",
        snapshot=item,
    )
    assert result["ok"] is True
    assert result["decision"] == "duplicate"
    assert result["event"]["kind"] == "duplicate"
    refreshed = build_post_sale_review_queue(
        data_dir=data_dir, sealed=_sealed_fixture(), board=_board_fixture()
    )
    assert all(row["review_id"] != rid for row in refreshed["active"])
    assert all(
        row.get("tag") != "reply" or row.get("parent_review_id") != rid
        for row in refreshed["active"]
    )
    labels = load_post_sale_review_labels(data_dir)
    assert rid in labels["actioned_review_ids"]
    assert any(row.get("kind") == "duplicate" for row in labels["events"])
    assert labels["active_replies"] == []


def test_nested_snapshot_batch_preserves_identity(tmp_path: Path):
    """Bridge UI nests snapshot; batch must still spawn a usable reply card."""
    from value_investor.post_sale_review_actions import run_post_sale_review_action_batch

    data_dir = tmp_path
    (data_dir / "sealed_lifecycle.json").write_text("{}", encoding="utf-8")
    queue = build_post_sale_review_queue(
        data_dir=data_dir,
        sealed=_sealed_fixture(),
        board=_board_fixture(),
    )
    item = next(row for row in queue["active"] if row["ticker"] == "BBB.L")
    # Persist queue so _resolve_snapshot can heal if needed.
    refresh_post_sale_review_queue(
        data_dir=data_dir,
        store_path=data_dir / "post_sale_review_queue.json",
        persist=True,
    )
    batch = run_post_sale_review_action_batch(
        data_dir,
        [
            {
                "review_id": item["review_id"],
                "decision": "comment",
                "text": "Already saw this on N206",
                "tag": "new",
                "snapshot": item,
            }
        ],
        source="test",
        acted_by="test",
    )
    assert batch["ok"] is True
    labels = load_post_sale_review_labels(data_dir)
    assert labels["active_replies"] == []
    reply_events = [row for row in labels["events"] if row.get("kind") == "reply"]
    assert reply_events
    comment_events = [row for row in labels["events"] if row.get("kind") == "comment"]
    assert comment_events
    assert comment_events[-1].get("snapshot", {}).get("ticker") == "BBB.L"
    after = build_post_sale_review_queue(
        data_dir=data_dir, sealed=_sealed_fixture(), board=_board_fixture()
    )
    assert all(row["review_id"] != item["review_id"] for row in after["active"])
    assert all(row.get("tag") != "reply" for row in after["active"])
    assert all(row.get("ticker") != "BBB.L" or row.get("tag") != "reply" for row in after["active"])


def test_actioned_episode_key_keeps_jitter_fingerprint_cleared(tmp_path: Path):
    """Same calendar episode with a new review_id fingerprint stays cleared."""
    from value_investor.post_sale_review_labels import actioned_episode_keys

    sealed = _sealed_fixture()
    board = _board_fixture()
    base = build_post_sale_review_queue(data_dir=tmp_path, sealed=sealed, board=board)
    item = next(row for row in base["active"] if row["ticker"] == "AAA.L")
    ep = item["episode_key"]
    labels = {
        "actioned_review_ids": ["stale-fingerprint-from-old-seconds"],
        "events": [
            {
                "kind": "comment",
                "review_id": "stale-fingerprint-from-old-seconds",
                "text": "already reviewed",
                "snapshot": {
                    "episode_key": ep,
                    "ticker": item["ticker"],
                    "book_id": item["book_id"],
                    "book_tag": item["book_tag"],
                    "entry_at": item["entry_at"],
                    "exit_at": item["exit_at"],
                },
            }
        ],
        "active_replies": [],
    }
    assert ep in actioned_episode_keys(labels)
    payload = build_post_sale_review_queue(
        data_dir=tmp_path, sealed=sealed, board=board, labels=labels
    )
    assert all(row.get("episode_key") != ep for row in payload["active"])
    assert all(row.get("review_id") != item["review_id"] for row in payload["active"])


def test_resolve_snapshot_heals_from_labels_when_queue_cleared(tmp_path: Path):
    """Batch race: card already gone from active queue; heal identity from labels."""
    from value_investor.post_sale_review_actions import _resolve_snapshot
    from value_investor.post_sale_review_labels import record_accept
    from value_investor.storage import write_json

    data_dir = tmp_path
    (data_dir / "sealed_lifecycle.json").write_text("{}", encoding="utf-8")
    queue = build_post_sale_review_queue(
        data_dir=data_dir, sealed=_sealed_fixture(), board=_board_fixture()
    )
    item = next(row for row in queue["active"] if row["ticker"] == "BBB.L")
    write_json(data_dir / "post_sale_review_queue.json", {"active": []}, compact=False)
    record_accept(
        data_dir,
        review_id=item["review_id"],
        snapshot={
            "ticker": item["ticker"],
            "book_tag": item["book_tag"],
            "book_id": item["book_id"],
            "episode_key": item["episode_key"],
            "entry_at": item["entry_at"],
            "exit_at": item["exit_at"],
        },
    )
    healed = _resolve_snapshot(data_dir, item["review_id"], {})
    assert healed.get("ticker") == "BBB.L"
    assert healed.get("book_tag") or healed.get("book_id")


def test_reply_rebuild_preserves_comment_dialogue(tmp_path: Path):
    """Legacy active_replies must not re-enter active; dialogue stays in history events."""
    from value_investor.post_sale_review_opinion import extend_dialogue_for_comment_reply

    dialogue = extend_dialogue_for_comment_reply(
        prior_dialogue=[{"kind": "initial_opinion", "text": "seed"}],
        item={"ticker": "AAA.L", "book_tag": "N200"},
        owner_comment="Premature sell",
        reply_text="Acknowledged premature sell.",
        reply_kind="deterministic_contextual",
    )
    kinds = [str(t.get("kind")) for t in dialogue if isinstance(t, dict)]
    assert "comment" in kinds
    assert "reply" in kinds
    labels = {
        "actioned_review_ids": ["parent-1"],
        "events": [
            {
                "kind": "comment",
                "review_id": "parent-1",
                "text": "Premature sell",
                "snapshot": {
                    "ticker": "AAA.L",
                    "book_id": "n200",
                    "book_tag": "N200",
                    "episode_key": "n200|AAA.L|2026-10-01|2026-10-20",
                    "entry_at": "2026-10-01T10:00:00+00:00",
                    "exit_at": "2026-10-20T10:00:00+00:00",
                },
            },
            {
                "kind": "reply",
                "review_id": "reply:keep",
                "parent_review_id": "parent-1",
                "text": "Acknowledged premature sell.",
            },
        ],
        "active_replies": [
            {
                "review_id": "reply:keep",
                "parent_review_id": "parent-1",
                "tag": "reply",
                "ticker": "AAA.L",
                "book_tag": "N200",
                "book_id": "n200",
                "owner_comment": "Premature sell",
                "reply_text": "Acknowledged premature sell.",
                "dialogue": dialogue,
            }
        ],
    }
    payload = build_post_sale_review_queue(
        data_dir=tmp_path,
        sealed=_sealed_fixture(),
        board=_board_fixture(),
        labels=labels,
    )
    assert all(row.get("review_id") != "reply:keep" for row in payload["active"])
    assert all(row.get("tag") != "reply" for row in payload["active"])


def test_commented_episode_does_not_reappear_in_active(tmp_path: Path):
    """Regression: Comment clears active; refresh must not bounce the episode back."""
    data_dir = tmp_path
    (data_dir / "sealed_lifecycle.json").write_text("{}", encoding="utf-8")
    queue = build_post_sale_review_queue(
        data_dir=data_dir,
        sealed=_sealed_fixture(),
        board=_board_fixture(),
    )
    item = next(row for row in queue["active"] if row["ticker"] == "AAA.L")
    rid = item["review_id"]
    ep = item["episode_key"]
    result = run_post_sale_review_action(
        data_dir,
        review_id=rid,
        decision="comment",
        text="Already reviewed this exit",
        tag_at_action="new",
        source="test",
        snapshot=item,
    )
    assert result["ok"] is True
    # Simulate GHA refresh + client overlay inputs: labels catch up, queue rebuilds.
    refreshed = refresh_post_sale_review_queue(
        data_dir=data_dir,
        store_path=data_dir / "post_sale_review_queue.json",
        persist=True,
    )
    assert all(row.get("review_id") != rid for row in refreshed["active"])
    assert all(row.get("episode_key") != ep for row in refreshed["active"])
    assert all(row.get("tag") != "reply" for row in refreshed["active"])
    assert refreshed["reply_count"] == 0
    labels = load_post_sale_review_labels(data_dir)
    assert rid in labels["actioned_review_ids"]
    assert labels.get("active_replies") == []
    assert any(row.get("kind") == "comment" for row in labels["events"])
    assert any(row.get("kind") == "reply" for row in labels["events"])
    # Fingerprint jitter: new review_id, same episode_key — still cleared.
    jitter_labels = {
        "actioned_review_ids": list(labels["actioned_review_ids"]),
        "events": list(labels["events"]),
        "active_replies": [
            {"review_id": "reply:legacy", "tag": "reply", "ticker": "AAA.L", "book_tag": "N200"}
        ],
    }
    again = build_post_sale_review_queue(
        data_dir=data_dir,
        sealed=_sealed_fixture(),
        board=_board_fixture(),
        labels=jitter_labels,
    )
    assert all(row.get("episode_key") != ep for row in again["active"])
    assert all(row.get("tag") != "reply" for row in again["active"])
