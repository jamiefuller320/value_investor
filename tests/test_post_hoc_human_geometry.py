"""N229 — post-hoc human chart geometry (schema + fail-closed reply bind)."""

from __future__ import annotations

from pathlib import Path

from value_investor.post_hoc_human_geometry import (
    geometry_unread_banner,
    human_geometry_as_pattern_marks,
    normalize_post_hoc_human_geometry,
    readable_geometries,
    serialize_geometry_for_prompt,
)
from value_investor.post_sale_review_labels import record_comment
from value_investor.post_sale_review_opinion import (
    build_contextual_reply_text,
    build_llm_reply_prompt,
    generate_factory_reply,
)


def _valid_geo(**overrides):
    base = {
        "geometry_id": "g1",
        "review_id": "rev-1",
        "chart": "episode",
        "drawn_at": "2026-10-30T12:00:00+00:00",
        "post_hoc": True,
        "elements": [
            {"type": "highlight", "t0": "2026-09-01", "t1": "2026-09-15"},
            {
                "type": "line",
                "t0": "2026-09-01",
                "y0": 10.5,
                "t1": "2026-09-20",
                "y1": 12.0,
            },
            {
                "type": "parallel_pair",
                "line_a": {"t0": "2026-09-01", "y0": 9.0, "t1": "2026-09-20", "y1": 11.0},
                "line_b": {"t0": "2026-09-01", "y0": 8.0, "t1": "2026-09-20", "y1": 10.0},
            },
        ],
        "readable": True,
        "influences_live": False,
    }
    base.update(overrides)
    return base


def test_normalize_readable_and_marks():
    rows = normalize_post_hoc_human_geometry([_valid_geo()], review_id="rev-1")
    assert len(rows) == 1
    assert rows[0]["readable"] is True
    assert rows[0]["post_hoc"] is True
    assert rows[0]["influences_live"] is False
    assert rows[0]["source"] == "owner"
    assert len(rows[0]["elements"]) == 3
    prompt = serialize_geometry_for_prompt(rows)
    assert prompt is not None
    assert prompt["influences_live"] is False
    marks = human_geometry_as_pattern_marks(rows)
    assert marks
    assert all(m.get("source") == "owner" for m in marks)
    assert all(m.get("influences_live") is False for m in marks)
    assert any(m.get("type") == "region" for m in marks)
    assert any(m.get("type") == "trend_line" for m in marks)


def test_fail_closed_invalid_unread():
    bad = normalize_post_hoc_human_geometry(
        [
            {
                "chart": "not_a_chart",
                "elements": [{"type": "highlight", "t0": "2026-01-01", "t1": "2026-01-02"}],
            },
            {
                "chart": "episode",
                "elements": [{"type": "line", "t0": "x", "y0": "nope"}],
            },
            {
                "chart": "wider_tf",
                "elements": [{"type": "highlight", "t0": "2026-01-01", "t1": "2026-01-02"}],
                "readable": False,
            },
        ],
        review_id="r",
    )
    assert all(row["readable"] is False for row in bad)
    assert readable_geometries(bad) == []
    assert serialize_geometry_for_prompt(bad) is None
    banner = geometry_unread_banner(bad)
    assert banner and "unread" in banner.lower()


def test_llm_prompt_includes_readable_only():
    item = {
        "book_tag": "N206",
        "ticker": "AAA.L",
        "entry_at": "2026-09-01",
        "exit_at": "2026-09-20",
        "hold_days": 14,
        "return_pct": -2.0,
        "sell_decision": {"code": "tech_exit", "label": "Tech", "join_ok": True},
        "buy_decision": {"code": "buy_tier", "label": "Buy tier", "join_ok": True},
    }
    good = normalize_post_hoc_human_geometry([_valid_geo()], review_id="rev-1")
    prompt = build_llm_reply_prompt(
        owner_comment="Support held here",
        item=item,
        post_hoc_human_geometry=good,
    )
    assert "post_hoc_human_geometry" in prompt
    assert "owner_highlight" not in prompt or "highlight" in prompt
    assert '"chart": "episode"' in prompt or '"chart": "episode"' in prompt.replace("'", '"')

    unread = normalize_post_hoc_human_geometry(
        [{"chart": "episode", "elements": [{"type": "bogus"}], "readable": False}],
        review_id="rev-1",
    )
    prompt_bad = build_llm_reply_prompt(
        owner_comment="Support held here",
        item=item,
        post_hoc_human_geometry=unread,
    )
    # Rules text may mention the field name; payload must omit readable geometry.
    assert '"post_hoc_human_geometry":' not in prompt_bad
    assert "geometry_unread" in prompt_bad
    # Must not invent coordinates from unread input.
    assert "12.0" not in prompt_bad


def test_contextual_reply_mentions_geometry():
    item = {
        "book_tag": "control",
        "ticker": "BBB.L",
        "hold_days": 5,
        "return_pct": 1.0,
        "buy_decision": {"label": "Buy", "join_ok": True},
        "sell_decision": {"label": "Sell", "code": "leave_buy_tier", "join_ok": True},
    }
    geo = normalize_post_hoc_human_geometry([_valid_geo(chart="wider_tf")], review_id="r")
    text = build_contextual_reply_text(
        owner_comment="Missed the climb",
        item=item,
        post_hoc_human_geometry=geo,
    )
    assert "Owner chart geometry" in text
    assert "wider_tf" in text
    assert "influences_live=false" in text


def test_record_comment_persists_geometry(tmp_path: Path):
    snap = {
        "book_tag": "N206",
        "book_id": "n206",
        "ticker": "SHL.AX",
        "entry_at": "2026-10-01T00:00:00+00:00",
        "exit_at": "2026-10-10T00:00:00+00:00",
        "hold_days": 7,
        "return_pct": 1.2,
        "exit_kind": "just_sold",
        "basis_label": "fair_cost_episode",
        "buy_decision": {"code": "buy_tier", "label": "Buy tier", "join_ok": True},
        "sell_decision": {"code": "tech_exit", "label": "Tech", "join_ok": True},
    }
    geo = [
        {
            "chart": "episode",
            "elements": [
                {"type": "highlight", "t0": "2026-10-02", "t1": "2026-10-05"},
            ],
            "readable": True,
            "post_hoc": True,
        }
    ]
    event = record_comment(
        tmp_path,
        review_id="psr:test:1",
        text="Band of support",
        snapshot=snap,
        allow_llm_reply=False,
        post_hoc_human_geometry=geo,
    )
    assert event.get("post_hoc_human_geometry")
    assert event["post_hoc_human_geometry"][0]["readable"] is True
    reply = event["reply"]
    assert reply.get("post_hoc_human_geometry")
    dialogue = reply.get("dialogue") or []
    owner_turns = [t for t in dialogue if t.get("kind") == "comment"]
    assert owner_turns
    assert owner_turns[-1].get("post_hoc_human_geometry")
    assert "Owner chart geometry" in reply["reply_text"]


def test_generate_factory_reply_fail_closed_unread():
    reply = generate_factory_reply(
        owner_comment="See the line",
        item={"book_tag": "N206", "ticker": "X.L", "hold_days": 3, "return_pct": 0},
        allow_llm=False,
        post_hoc_human_geometry=[
            {"chart": "episode", "elements": [{"type": "nope"}], "readable": False}
        ],
    )
    assert reply["influences_live"] is False
    assert "unread" in reply["text"].lower() or "schema-invalid" in reply["text"].lower()
    # No invented prices.
    assert "y0" not in reply["text"]
