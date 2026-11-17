"""Observe-only CHF, SEK, HKD and SGD closes for the sterling proof bars."""

from __future__ import annotations

import inspect
import json
from datetime import UTC, date, datetime
from pathlib import Path

from value_investor.ops_monitor import check_strategy_book_fx_rates, collect_ops_findings
from value_investor.strategy_book_fx_rates import (
    HISTORY_START,
    TITLE_INCOMPLETE,
    TITLE_INFO,
    TITLE_MISSING,
    TITLE_STALE,
    refresh_store,
    write_store,
)
from value_investor.strategy_book_proof import FxHistory


def _fetcher(rows: dict[str, list[tuple[date, float]]]):
    def fetch(symbol: str, start: date, end: date) -> list[tuple[date, float]]:
        assert start == HISTORY_START
        assert end >= start
        return list(rows.get(symbol, []))

    return fetch


def _good_rows() -> dict[str, list[tuple[date, float]]]:
    return {
        "CHFUSD=X": [(date(2026, 11, 10), 1.12), (date(2026, 11, 12), 1.13)],
        "SEKUSD=X": [(date(2026, 11, 10), 0.105)],
        "HKDUSD=X": [(date(2026, 11, 10), 0.128), (date(2026, 11, 12), 0.129)],
        "SGDUSD=X": [(date(2026, 11, 10), 0.77)],
    }


def test_refresh_keeps_the_first_close_and_refuses_an_inverted_quote(tmp_path: Path) -> None:
    first = refresh_store(tmp_path, fetcher=_fetcher(_good_rows()), today=date(2026, 11, 17))
    write_store(tmp_path, first)
    assert first["influences_live"] is False
    assert first["changes_fair_cost"] is False

    def later(symbol: str, start: date, end: date) -> list[tuple[date, float]]:
        if symbol == "HKDUSD=X":
            # Same session at a different close, plus a new session. Both sit in band.
            return [(date(2026, 11, 10), 0.127), (date(2026, 11, 13), 0.130)]
        if symbol == "CHFUSD=X":
            return [(date(2026, 11, 10), 0.50)]  # outside 0.8–1.6
        return _fetcher(_good_rows())(symbol, start, end)

    second = refresh_store(tmp_path, fetcher=later, today=date(2026, 11, 17))
    hkd = {row["as_of"]: row["value"] for row in second["pairs"]["HKD"]}
    assert hkd["2026-11-10"] == 0.128
    assert hkd["2026-11-13"] == 0.13
    chf = {row["as_of"]: row["value"] for row in second["pairs"]["CHF"]}
    assert chf == {"2026-11-10": 1.12, "2026-11-12": 1.13}
    assert any(item.startswith("CHF:") for item in second["errors"])


def test_proof_uses_the_observe_store_and_not_a_later_session(tmp_path: Path) -> None:
    macro = tmp_path / "docs" / "data" / "library" / "macro"
    macro.mkdir(parents=True)
    (macro / "2026-11-10.json").write_text(
        json.dumps(
            {"domains": {"uk": {"markers": {"gbp_usd": {"value": 1.25, "as_of": "2026-11-10"}}}}}
        ),
        encoding="utf-8",
    )
    payload = refresh_store(tmp_path, fetcher=_fetcher(_good_rows()), today=date(2026, 11, 17))
    write_store(tmp_path, payload)
    history = FxHistory.load(tmp_path)
    # 11 Nov still sees the 10 Nov HKD close, not the 12 Nov close.
    rate, reason = history.gbp_per_unit("HKD", date(2026, 11, 11))
    assert reason == ""
    assert rate == 0.128 / 1.25
    later, _later_reason = history.gbp_per_unit("HKD", date(2026, 11, 12))
    assert later == 0.129 / 1.25
    missing, missing_reason = history.gbp_per_unit("HKD", date(2026, 11, 9))
    assert missing is None
    assert "2026-11-09" in missing_reason
    assert "HKD" not in history.to_meta()["no_daily_series"]


def test_missing_store_still_names_the_gap(tmp_path: Path) -> None:
    history = FxHistory.load(tmp_path)
    rate, reason = history.gbp_per_unit("CHF", date(2026, 11, 11))
    assert rate is None
    assert "CHF" in reason
    assert "CHF" in history.to_meta()["no_daily_series"]


def test_findings_and_ops_check(tmp_path: Path) -> None:
    now = datetime(2026, 11, 17, tzinfo=UTC)
    missing = check_strategy_book_fx_rates(repo_root=tmp_path, now=now)
    assert missing[0].title == TITLE_MISSING
    assert missing[0].auto_fixable is False

    payload = refresh_store(tmp_path, fetcher=_fetcher(_good_rows()), today=date(2026, 11, 17))
    payload["pairs"]["SEK"] = []
    write_store(tmp_path, payload)
    incomplete = check_strategy_book_fx_rates(repo_root=tmp_path, now=now)
    assert incomplete[0].title == TITLE_INCOMPLETE

    payload["pairs"]["SEK"] = [{"as_of": "2026-11-10", "value": 0.105}]
    payload["generated_at"] = "2026-11-01T00:00:00+00:00"
    write_store(tmp_path, payload)
    stale = check_strategy_book_fx_rates(repo_root=tmp_path, now=now)
    assert stale[0].title == TITLE_STALE

    payload["generated_at"] = "2026-11-17T00:00:00+00:00"
    write_store(tmp_path, payload)
    fresh = check_strategy_book_fx_rates(repo_root=tmp_path, now=now)
    assert fresh[0].title == TITLE_INFO
    assert fresh[0].auto_fixable is False
    assert "check_strategy_book_fx_rates" in inspect.getsource(collect_ops_findings)
