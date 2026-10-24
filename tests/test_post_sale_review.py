"""Post-sale review queue + Accept/Comment reply stub (Package M)."""

from __future__ import annotations

from pathlib import Path

from value_investor.post_sale_review import (
    CONTROL_BOOK_ID,
    build_post_sale_review_queue,
    ops_findings_from_queue,
    refresh_post_sale_review_queue,
    review_fingerprint,
    wider_tf_window,
)
from value_investor.post_sale_review_actions import run_post_sale_review_action
from value_investor.post_sale_review_labels import (
    REPLY_STUB_TEXT,
    comments_awaiting_reply,
    load_post_sale_review_labels,
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
    comment = run_post_sale_review_action(
        data_dir,
        review_id=control["review_id"],
        decision="comment",
        text="Missed climbing wider TF",
        tag_at_action="new",
        source="test",
        snapshot=control,
    )
    assert comment["ok"] is True
    reply = comment["event"]["reply"]
    assert reply["tag"] == "reply"
    assert REPLY_STUB_TEXT.split(".")[0] in reply["reply_text"]

    after = build_post_sale_review_queue(
        data_dir=data_dir, sealed=_sealed_fixture(), board=_board_fixture()
    )
    assert all(row["review_id"] != control["review_id"] for row in after["active"])
    reply_rows = [row for row in after["active"] if row["tag"] == "reply"]
    assert len(reply_rows) == 1
    assert reply_rows[0]["owner_comment"] == "Missed climbing wider TF"

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
