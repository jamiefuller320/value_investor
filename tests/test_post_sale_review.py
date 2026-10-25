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
    reply_rows = [row for row in after["active"] if row["tag"] == "reply"]
    assert len(reply_rows) == 1
    assert reply_rows[0]["owner_comment"] == "Missed climbing wider TF"
    assert reply_rows[0]["llm_opinion"]
    assert len(reply_rows[0]["dialogue"]) >= 3

    # Accept the reply → clears again
    run_post_sale_review_action(
        data_dir,
        review_id=reply_rows[0]["review_id"],
        decision="accept",
        tag_at_action="reply",
        source="test",
        snapshot=reply_rows[0],
    )
    final = build_post_sale_review_queue(
        data_dir=data_dir, sealed=_sealed_fixture(), board=_board_fixture()
    )
    assert final["reply_count"] == 0
    labels = load_post_sale_review_labels(data_dir)
    assert comments_awaiting_reply(labels) == []
    kinds = [row["kind"] for row in labels["events"]]
    assert kinds.count("accept") == 2
    assert kinds.count("comment") == 1
    assert kinds.count("reply") == 1


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
    """Unusable ``?`` reply leftovers must not clutter the active queue."""
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
    reply_ids = {row["review_id"] for row in payload["active"] if row.get("tag") == "reply"}
    assert "reply:blank" not in reply_ids
    assert "reply:ok" in reply_ids
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
    assert labels["active_replies"]
    reply = labels["active_replies"][-1]
    assert reply.get("ticker") == "BBB.L"
    assert reply.get("book_tag") or reply.get("book_id")
    after = build_post_sale_review_queue(
        data_dir=data_dir, sealed=_sealed_fixture(), board=_board_fixture()
    )
    assert all(row["review_id"] != item["review_id"] for row in after["active"])
    assert any(
        row.get("tag") == "reply" and row.get("ticker") == "BBB.L" for row in after["active"]
    )
