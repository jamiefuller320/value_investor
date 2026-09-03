"""Tests for depth-first euro_depth composite market."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from value_investor.data_library import (
    EURO_DEPTH_COMPONENTS,
    MARKET_REGISTRY,
    PREQUALIFIED_YAHOO_MARKETS,
    fetch_euro_depth_constituents,
    refresh_constituents,
)
from value_investor.fx import currency_for_market, currency_for_ticker
from value_investor.library_sim import MARKET_BENCHMARKS, observe_sim_markets_for_policy
from value_investor.market_paper_shard import session_defaults_for_market
from value_investor.market_shard_phases import (
    PHASE1_MIN_SCREEN_ARCHIVES,
    evaluate_market_phase,
    phase1_gate_met,
)
from value_investor.research.filings import resolve_filings_regime
from value_investor.storage import write_json


def test_euro_depth_registered_and_prequalified():
    assert "euro_depth" in MARKET_REGISTRY
    assert "euro_depth" in PREQUALIFIED_YAHOO_MARKETS
    assert MARKET_BENCHMARKS["euro_depth"] == "^STOXX50E"
    assert session_defaults_for_market("euro_depth")["timezone"] == "Europe/Paris"


def test_fetch_euro_depth_unions_disk_components(tmp_path: Path, monkeypatch):
    root = tmp_path / "library"
    for mid, tickers in [
        ("euro_stoxx50", ["SAP.DE", "AIR.PA"]),
        ("aex", ["ASML.AS", "SAP.DE"]),  # SAP overlap — STOXX wins
        ("bel20", ["ABI.BR"]),
        ("smi", ["NESN.SW"]),
        ("omxs30", ["ABB.ST"]),
        ("atx", ["EBS.VI"]),
        ("psi20", ["EDP.LS"]),
        ("iseq20", ["A5G.IR"]),
    ]:
        cdir = root / "markets" / mid / "constituents"
        cdir.mkdir(parents=True)
        write_json(
            cdir / "latest.json",
            [{"ticker": t, "name": t, "sector": "X", "market": mid} for t in tickers],
            compact=False,
        )

    import value_investor.data_library as dl

    def _boom(mid: str = ""):
        def _inner() -> pd.DataFrame:
            raise RuntimeError(mid)

        return _inner

    for mid in EURO_DEPTH_COMPONENTS:
        monkeypatch.setitem(dl.CONSTITUENT_FETCHERS, mid, _boom(mid))

    frame = fetch_euro_depth_constituents(library_root=root)
    assert len(frame) == 9  # 10 rows minus 1 SAP.DE overlap
    assert set(frame["ticker"]) == {
        "SAP.DE",
        "AIR.PA",
        "ASML.AS",
        "ABI.BR",
        "NESN.SW",
        "ABB.ST",
        "EBS.VI",
        "EDP.LS",
        "A5G.IR",
    }
    assert list(frame.loc[frame["ticker"] == "SAP.DE", "component_market"]) == ["euro_stoxx50"]
    assert (frame["market"] == "euro_depth").all()

    monkeypatch.setitem(dl.CONSTITUENT_FETCHERS, "euro_depth", lambda: frame)
    manifest = refresh_constituents(root, "euro_depth")
    assert manifest["ticker_count"] == 9


def test_euro_filings_regime_includes_periphery_and_depth():
    assert resolve_filings_regime("euro_depth", "SAP.DE") == "euro_filings"
    assert resolve_filings_regime("omxs30", "ABB.ST") == "euro_filings"
    assert resolve_filings_regime("atx", "EBS.VI") == "euro_filings"
    assert resolve_filings_regime("iseq20", "A5G.IR") == "euro_filings"
    assert resolve_filings_regime("smi", "NESN.SW") == "euro_filings"
    assert resolve_filings_regime("psi20", "EDP.LS") == "euro_filings"
    assert resolve_filings_regime(None, "ABB.ST") == "euro_filings"
    assert resolve_filings_regime(None, "EBS.VI") == "euro_filings"


def test_euro_depth_fx_suffix_first():
    assert currency_for_market("euro_depth") == "EUR"
    assert currency_for_ticker("ABB.ST", market="euro_depth") == "SEK"
    assert currency_for_ticker("NESN.SW", market="euro_depth") == "CHF"
    assert currency_for_ticker("SAP.DE", market="euro_depth") == "EUR"
    assert currency_for_ticker("AAPL", market="ftse350") == "GBP"


def test_observe_sim_explicit_euro_depth():
    policy = {
        "ladder": {
            "observe_sim_after_screen": True,
            "observe_sim_markets_mode": "explicit",
            "observe_sim_markets": ["euro_depth"],
            "observe_sim_include_ingest_profile": False,
        }
    }
    assert observe_sim_markets_for_policy(policy) == ["euro_depth"]


def test_observe_sim_ingest_profile_adds_sprint_markets():
    policy = {
        "focus_market": "euro_depth",
        "ingest_parallel_sprint": ["sp500"],
        "ingest_parallel_sprint_2": ["asx200"],
        "ladder": {
            "observe_sim_after_screen": True,
            "observe_sim_markets_mode": "explicit",
            "observe_sim_markets": ["euro_depth"],
        },
    }
    assert observe_sim_markets_for_policy(policy) == ["euro_depth", "sp500", "asx200"]
    assert "euro_depth" in MARKET_BENCHMARKS
    assert "asx200" in MARKET_BENCHMARKS


def test_phase1_gate_skips_ai_when_policy_disables(tmp_path: Path):
    root = tmp_path / "library"
    market_id = "euro_depth"
    screen_dir = root / "markets" / market_id / "screen"
    for idx in range(PHASE1_MIN_SCREEN_ARCHIVES):
        stamp = f"202607{idx + 1:02d}_120000"
        screen_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame([{"ticker": "SAP.DE", "signal": "buy"}]).to_csv(
            screen_dir / f"signals_{stamp}.csv", index=False
        )
        pd.DataFrame([{"ticker": "SAP.DE", "last_price": 100.0}]).to_csv(
            screen_dir / f"universe_{stamp}.csv", index=False
        )
    sim_dir = screen_dir / "sim"
    sim_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        sim_dir / "observe_summary.json",
        {
            "snapshot_count": PHASE1_MIN_SCREEN_ARCHIVES,
            "tracks": {
                "ai_judgment": {"excess_return": -0.05},
                "screen_rules": {"excess_return": 0.02},
            },
        },
        compact=False,
    )
    ok_default, detail = phase1_gate_met(root, market_id)
    assert ok_default is False
    assert detail["ai_beat_rules_observe_sim"] is False

    policy = {"ladder": {"phase1_require_ai_beat_rules": False}}
    ok_relaxed, detail2 = phase1_gate_met(root, market_id, policy=policy)
    assert ok_relaxed is True
    assert detail2["phase1_require_ai_beat_rules"] is False

    evaluation = evaluate_market_phase(
        market_id,
        library_root=root,
        policy={
            "ladder": {
                "phase1_require_ai_beat_rules": False,
                "weekly_paper_shard_after_screen": True,
                "weekly_paper_shard_markets": ["euro_depth"],
            }
        },
    )
    assert evaluation["phase1_ready"] is True
    assert "AI-judgment must beat rules" not in " ".join(evaluation.get("blockers") or [])
