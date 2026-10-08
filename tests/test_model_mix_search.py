"""Pre-registered model-mix search (hms-v1) on synthetic replay builds (no licensed rows)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from value_investor import historical_screen_replay as hsr
from value_investor import model_mix_search as mm
from value_investor.models import ALL_MODELS

N = 40
DELISTED = 7


def _registration() -> dict:
    reg = json.loads(json.dumps(mm.load_registration()))
    reg["windows"] = {
        "development": {"first_entry": "2000-01-31", "last_entry": "2001-12-31"},
        "holdout": {"first_entry": "2002-01-31", "last_entry": "2002-12-31"},
    }
    reg["eligibility"].update(min_names_per_month=10, min_months=12)
    reg["overfitting"]["cscv_blocks"] = 4
    reg["objective"]["horizon_months"] = 12
    reg["objective"]["report_horizons_months"] = [3, 12]
    reg["screen_code_fingerprint"] = hsr.screen_code_fingerprint()
    reg["mix_code_fingerprint"] = mm.mix_code_fingerprint()
    return reg


def _build(root: Path, name: str, seed: int) -> Path:
    """Next month's drift follows a score that changes every month.

    ``earnings_yield`` and ``fcf_yield`` carry that score (duplicates),
    ``magic_formula`` a noisier copy, ``lynch_peg`` its reverse, and
    ``graham_defensive`` noise. Other models are absent; the panel signals and
    momentum are noise.
    """
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("1998-06-01", "2003-01-31")
    month_ends = pd.Series(days).groupby(days.to_period("M")).max().tolist()
    screens = [d for d in month_ends if d >= pd.Timestamp("1999-12-31")]
    signal_score = rng.uniform(size=(len(screens), N))
    noise = rng.uniform(size=(len(screens), N))
    drift = np.zeros((len(days), N))
    for m, start in enumerate(screens):
        end = screens[m + 1] if m + 1 < len(screens) else days[-1]
        drift[(days > start) & (days <= end)] = 0.004 * (signal_score[m] - 0.5)
    close = 50 * np.exp(np.cumsum(drift + rng.normal(0, 0.008, (len(days), N)), axis=0))
    last_day = int(np.searchsorted(days, pd.Timestamp("2001-06-15")))
    tickers = [f"U{i:02d}" for i in range(N)]

    daily_rows, sig_rows, panel_rows = [], [], []
    for i, ticker in enumerate(tickers):
        n = last_day if i == DELISTED else len(days)
        for k in range(n):
            c = close[k, i]
            daily_rows.append((ticker, days[k].date().isoformat(), c, c * 1.01, c * 0.99, c))
        for m, d in enumerate(screens):
            if i == DELISTED and d > days[n - 1]:
                continue
            s = float(signal_score[m, i])
            scores = {
                "earnings_yield": s,
                "fcf_yield": s,
                "magic_formula": 0.5 * s + 0.5 * float(noise[m, i]),
                "lynch_peg": 1.0 - s,
                "graham_defensive": float(rng.uniform()),
            }
            row = {
                "as_of": d.tz_localize("UTC"),
                "ticker": ticker,
                "signal": "buy" if i % 3 == 0 else "hold",
                "conviction_score": float(i),
                "sector": "Industrials",
                "earnings_yield": 0.02 + 0.002 * i,
                "composite_score": float(rng.uniform()),
                "data_quality_score": 1.0,
            }
            for model, value in scores.items():
                row[f"{hsr.MODEL_PASS_PREFIX}{model}"] = int(value > 0.5)
                row[f"{hsr.MODEL_SCORE_PREFIX}{model}"] = value
            sig_rows.append(row)
            assets = float(rng.uniform(1e9, 2e9))
            panel_rows.append(
                {
                    "as_of": d.date().isoformat(),
                    "ticker": ticker,
                    "market_cap": 1e9 * (1 + i),
                    "dividend_yield": 2.0,
                    "gross_margin": float(rng.uniform(0.2, 0.6)),
                    "total_revenue": float(rng.uniform(1e9, 3e9)),
                    "total_assets": assets,
                    "total_assets_prev": assets * float(rng.uniform(0.8, 1.2)),
                    "net_income": float(rng.uniform(5e7, 2e8)),
                    "operating_cashflow": float(rng.uniform(5e7, 2e8)),
                    "shares_outstanding": 1e8,
                    "shares_outstanding_prev": 1e8 * float(rng.uniform(0.95, 1.05)),
                }
            )
    build = root / name
    build.mkdir()
    pd.DataFrame(daily_rows, columns=["ticker", "date", "open", "high", "low", "close"]).to_csv(
        build / "daily.csv.gz", index=False
    )
    pd.DataFrame(panel_rows).to_csv(build / "panel.csv.gz", index=False)
    pd.DataFrame([{"ticker": tickers[DELISTED], "haircut": 0.0}]).to_csv(
        build / "terminal_baseline.csv", index=False
    )
    panel = pd.read_csv(build / "panel.csv.gz")
    for variant, transform in (("baseline", None), (mm.SCORE_VARIANT, mm.SCORE_VARIANT)):
        cache = build / hsr.signal_cache_name(variant)
        pd.DataFrame(sig_rows).to_csv(cache, index=False)
        key = hsr.signal_cache_key(panel, transform)
        cache.with_name(cache.name + ".key.json").write_text(json.dumps(key))
    return build


@pytest.fixture(scope="module")
def builds(tmp_path_factory) -> dict[str, Path]:
    root = tmp_path_factory.mktemp("hms")
    return {"sp500": _build(root, "large", 3), "midcap": _build(root, "mid", 4)}


@pytest.fixture
def reg_path(tmp_path: Path) -> Path:
    path = tmp_path / "hms.json"
    path.write_text(json.dumps(_registration()))
    return path


def test_committed_registration_matches_code():
    reg = mm.load_registration()
    specs = mm.candidate_specs(reg)
    assert reg["candidates"]["models"]["ids"] == [m.id for m in ALL_MODELS]
    assert len(specs) == 27
    published = {s["id"]: s["direction"] for s in reg["candidates"]["published"]}
    assert published == {
        "gross_profitability": 1,
        "accruals": -1,
        "net_share_issuance": -1,
        "asset_growth": -1,
        "momentum_12_1": 1,
    }
    assert reg["screen_code_fingerprint"] == hsr.screen_code_fingerprint()
    assert reg["mix_code_fingerprint"] == mm.mix_code_fingerprint()
    for universe, path in (
        ("sp500", hsr.DEFAULT_REGISTRATION_PATH),
        ("midcap", hsr.MIDCAP_REGISTRATION_PATH),
    ):
        replay = hsr.load_registration(path)
        assert reg["universes"][universe]["cost_base_per_side"] == replay["costs"]["base_per_side"]
        assert reg["windows"]["development"] == replay["windows"]["development"]
        assert (
            reg["windows"]["holdout"]["first_entry"] == replay["windows"]["holdout"]["first_entry"]
        )
    assert all(a["before_data"] for a in reg["amendments"])


def test_published_signals_follow_their_definitions():
    panel = pd.DataFrame(
        {
            "gross_margin": [0.5],
            "total_revenue": [200.0],
            "total_assets": [400.0],
            "total_assets_prev": [320.0],
            "net_income": [30.0],
            "operating_cashflow": [50.0],
            "shares_outstanding": [110.0],
            "shares_outstanding_prev": [100.0],
        }
    )
    assert mm.gross_profitability(panel).iloc[0] == pytest.approx(0.25)
    assert mm.accruals(panel).iloc[0] == pytest.approx(-0.05)
    assert mm.net_share_issuance(panel).iloc[0] == pytest.approx(0.10)
    assert mm.asset_growth(panel).iloc[0] == pytest.approx(0.25)
    assert mm.asset_growth(panel.assign(total_assets_prev=0.0)).isna().all()


def test_selection_rule_keeps_reliable_drops_duplicates():
    def stats(mean: float, eligible: bool = True, coverage: bool = True) -> dict:
        return {
            "eligible": eligible,
            "coverage_ok": coverage,
            "mean_ic": {"mean": mean, "low": mean - 0.01, "high": mean + 0.01},
        }

    per_universe = {
        "a": stats(0.05),
        "b": stats(0.05),
        "c": stats(0.03),
        "d": stats(0.04, eligible=False),
        "e": stats(0.0, eligible=False, coverage=False),
    }
    ids = list(per_universe)
    corr = pd.DataFrame(0.1, index=ids, columns=ids)
    corr.loc["a", "b"] = corr.loc["b", "a"] = 0.95
    reg = {"redundancy": {"max_mean_rank_correlation": 0.8}}
    other = {**per_universe, "c": stats(0.03, eligible=False)}
    one = mm.select_candidates({"sp500": per_universe}, {"sp500": corr}, reg)
    assert one["kept"] == ["a", "c"] and one["dropped_redundant"] == {"b": "a"}
    assert one["covered"] == ["a", "b", "c", "d"]
    both = mm.select_candidates(
        {"sp500": per_universe, "midcap": other}, {"sp500": corr, "midcap": corr}, reg
    )
    assert both["kept"] == ["a"] and both["eligible"] == ["a", "b"]


def test_search_reveal_and_gates(builds, reg_path: Path, tmp_path: Path):
    store = tmp_path / hsr.MODEL_MIX_STORE_NAME
    replay_store = tmp_path / hsr.DEFAULT_STORE_PATH.name
    no_rule_search = tmp_path / "no-hrs.json"

    with pytest.raises(ValueError, match="model-mix search"):
        hsr.run_replay(
            tmp_path / "x" / "panel.csv",
            tmp_path / "x" / "prices.csv",
            store_path=replay_store,
            reveal_holdout=True,
            rule_search_registration_path=no_rule_search,
            model_mix_registration_path=reg_path,
        )
    with pytest.raises(ValueError, match="No committed selection"):
        mm.reveal(builds, registration_path=reg_path, store_path=store)
    with pytest.raises(ValueError, match="required"):
        mm.search({"sp500": builds["sp500"]}, registration_path=reg_path, store_path=store)

    payload = mm.search(builds, registration_path=reg_path, store_path=store)
    result = payload["search"]
    selection = result["selection"]
    assert result["candidates_tested"] == 27
    assert selection["kept"][0] == "earnings_yield"
    assert "magic_formula" in selection["kept"]
    assert selection["dropped_redundant"]["fcf_yield"] == "earnings_yield"
    for absent in ("graham_defensive", "lynch_peg", "piotroski_f", "accruals"):
        assert absent not in selection["kept"]
    lynch = result["candidates"]["lynch_peg"]["sp500"]
    assert "ic_not_reliably_positive" in lynch["reasons"]
    assert result["candidates"]["piotroski_f"]["midcap"]["reasons"][0] == "coverage"
    for universe in ("sp500", "midcap"):
        books = result["books"][universe]
        assert books["mix"]["months"] == 24
        assert (
            books["mix"]["annualised_excess_plain_value"]
            > books["frozen_composite"]["annualised_excess_plain_value"]
        )
        series = result["series"][universe]
        assert len(series["mix"]) == len(series["plain_value"]) == 24
        assert len(series["candidate_rank_ic"]["earnings_yield"]) == 24
        assert set(result["overfitting"][universe]) == {"pbo_cscv", "deflated_sharpe_mix"}
    assert "U0" not in json.dumps(result)  # aggregates only, no per-name rows

    with pytest.raises(FileNotFoundError):
        hsr.run_replay(
            tmp_path / "x" / "panel.csv",
            tmp_path / "x" / "prices.csv",
            store_path=replay_store,
            reveal_holdout=True,
            rule_search_registration_path=no_rule_search,
            model_mix_registration_path=reg_path,
        )

    revealed = mm.reveal(builds, registration_path=reg_path, store_path=store)
    holdout = revealed["holdout"]
    verdicts = {"adds", "costs", "inconclusive", "too_thin"}
    for universe in ("sp500", "midcap"):
        for cost in ("base", "stress"):
            block = holdout["universes"][universe][cost]
            assert block["mix"]["months"] == 12
            assert block["mix_minus_frozen_composite"]["verdict"] in verdicts
            assert block["mix_minus_all_candidates"]["verdict"] in verdicts
            assert block["mix_verdict_vs_plain_value"] in {
                "pass",
                "fail",
                "inconclusive",
                "too_thin",
            }
            assert len(block["series"]["frozen_composite"]) == 12
        assert holdout["universes"][universe]["candidates"]["earnings_yield"]["months"] == 12
    assert holdout["decision"] in {"mix_adds_in_both", "partial", "no_gain_over_frozen_mix"}
    assert revealed["holdout_reveals"] == [{"at": holdout["run_at"], "evidence": True}]
    assert "U0" not in json.dumps(holdout)

    block = mm.status_block(reg_path, store)
    assert block["kept"] == selection["kept"]
    assert block["decision"] == holdout["decision"]
    assert mm.findings_from_block(block) == []
    mm.reveal(builds, registration_path=reg_path, store_path=store)
    titles = {
        f["title"] for f in hsr.findings_from_store({"model_mix": mm.status_block(reg_path, store)})
    }
    assert titles == {mm.HOLDOUT_REUSED_TITLE}
    with pytest.raises(ValueError, match="already revealed"):
        mm.search(builds, registration_path=reg_path, store_path=store)
    with pytest.raises(ValueError, match="already revealed"):
        mm.register(reg_path, store)


def test_search_refuses_after_a_replay_reveal(builds, reg_path: Path, tmp_path: Path):
    (tmp_path / hsr.MIDCAP_STORE_PATH.name).write_text(
        json.dumps({"holdout_reveals": [{"at": "2026-11-01", "evidence": True}]})
    )
    with pytest.raises(ValueError, match="would not be blind"):
        mm.search(builds, registration_path=reg_path, store_path=tmp_path / "hms-store.json")


def test_stale_registration_findings(tmp_path: Path):
    reg = _registration()
    reg["mix_code_fingerprint"] = "0" * 64
    path = tmp_path / "hms.json"
    path.write_text(json.dumps(reg))
    store = tmp_path / "store.json"
    titles = {f["title"] for f in mm.findings_from_block(mm.status_block(path, store))}
    assert titles == {mm.STALE_REGISTRATION_TITLE}
    store.write_text(json.dumps({"holdout_reveals": [{"at": "x", "evidence": True}]}))
    titles = {f["title"] for f in mm.findings_from_block(mm.status_block(path, store))}
    assert titles == {mm.STALE_VERDICT_TITLE}
    assert mm.status_block(tmp_path / "missing.json", store) is None
    with pytest.raises(ValueError, match="Mix code changed"):
        mm._check_fingerprints(reg)


def test_refuses_builds_inside_repo():
    with pytest.raises(ValueError, match="inside the repository"):
        mm.load_universe(hsr.REPO_ROOT / "docs", _registration(), "sp500")
