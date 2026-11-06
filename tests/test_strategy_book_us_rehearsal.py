"""Strategy-book US rehearsal runner, on synthetic Sharadar-shaped tables only.

Every value below is made up. The licence forbids committing vendor rows, so
the fixtures reuse Sharadar column names and nothing else.
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from value_investor import historical_screen_replay as hsr
from value_investor import strategy_book_observe as sbo
from value_investor import strategy_book_us_rehearsal as rehearsal
from value_investor import strategy_book_us_tape as tape
from value_investor.strategy_book_rules import RegistrationUnsigned

REPO = hsr.REPO_ROOT
CALENDAR = pd.bdate_range("1998-07-01", "2002-12-31")
NAMES = [f"Q{i:02d}" for i in range(44)]
DELISTED = {"Q05": pd.Timestamp("2001-08-15"), "Q27": pd.Timestamp("2001-11-15")}
MERGED = "Q27"
SP500_CORE = NAMES[:22]
REMOVED = ("Q20", pd.Timestamp("2000-09-12"))
ADDED = ("Q30", pd.Timestamp("2000-09-12"))
NO_HL = "no_hl"


def _paths(rng: np.random.Generator) -> dict[str, np.ndarray]:
    out = {}
    for index, ticker in enumerate(NAMES):
        drift = 0.0004 if index % 3 else -0.0002
        shocks = rng.normal(drift, 0.022, len(CALENDAR))
        shocks[rng.random(len(CALENDAR)) < 0.01] -= 0.08
        scale = 8.0 if index < 22 else 2.0
        out[ticker] = scale * (10 + index) * np.exp(np.cumsum(shocks))
    return out


def _stocks(paths: dict[str, np.ndarray], *, with_hl: bool) -> pd.DataFrame:
    frames = []
    for ticker, closes in paths.items():
        end = DELISTED.get(ticker, CALENDAR[-1])
        keep = CALENDAR <= end
        frame = pd.DataFrame(
            {
                "ticker": ticker,
                "date": CALENDAR[keep].strftime("%Y-%m-%d"),
                "open": closes[keep],
                "close": closes[keep],
                "closeadj": closes[keep],
                "closeunadj": closes[keep],
                "volume": 1000,
            }
        )
        if with_hl:
            frame.insert(3, "high", closes[keep] * 1.01)
            frame.insert(4, "low", closes[keep] * 0.99)
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def _fundamentals(paths: dict[str, np.ndarray]) -> pd.DataFrame:
    rows = []
    quarters = pd.date_range("1997-03-31", "2002-09-30", freq="QE")
    for index, ticker in enumerate(NAMES):
        growth = 1.03 if index % 4 else 0.96
        closes = paths[ticker]
        for q, cal in enumerate(quarters):
            filed = cal + pd.Timedelta(days=40)
            if ticker in DELISTED and filed > DELISTED[ticker]:
                break
            at = min(max(CALENDAR.searchsorted(filed), 0), len(CALENDAR) - 1)
            price = float(closes[at])
            quarter_rev = 100.0 * (1 + index) * growth**q
            ttm = sum(100.0 * (1 + index) * growth ** (q - j) for j in range(4))
            earnings = ttm * (0.12 if index % 5 else 0.02)
            shares = 1e6
            common = {
                "ticker": ticker,
                "calendardate": cal.date().isoformat(),
                "datekey": filed.date().isoformat(),
                "reportperiod": cal.date().isoformat(),
                "lastupdated": "2020-01-01",
                "marketcap": shares * price,
                "equity": ttm * 0.8,
                "debt": ttm * 0.3,
                "assets": ttm * 2.0,
                "assetsc": ttm * 0.7,
                "liabilities": ttm * 1.0,
                "liabilitiesc": ttm * 0.3,
                "cashneq": ttm * 0.1,
                "currentratio": 2.3,
                "divyield": 0.03,
                "roe": 0.15,
                "roa": 0.07,
                "netmargin": earnings / ttm,
                "grossmargin": 0.4,
                "ncfo": earnings * 1.4,
                "ebitda": earnings * 1.8,
                "intexp": 2.0,
                "bvps": ttm * 0.8 / shares,
                "sharesbas": shares,
            }
            rows.append(
                {
                    **common,
                    "dimension": "ART",
                    "revenue": ttm,
                    "netinccmn": earnings,
                    "opinc": earnings * 1.3,
                    "ebit": earnings * 1.4,
                    "eps": earnings / shares,
                    "epsdil": earnings / shares,
                    "fcf": earnings * 1.1,
                }
            )
            rows.append(
                {
                    **common,
                    "dimension": "ARQ",
                    "revenue": quarter_rev,
                    "netinccmn": earnings / 4,
                    "opinc": earnings * 1.3 / 4,
                    "ebit": earnings * 1.4 / 4,
                    "eps": earnings / shares / 4,
                    "epsdil": earnings / shares / 4,
                    "fcf": earnings * 1.1 / 4,
                }
            )
            rows.append({**common, "dimension": "MRT", "revenue": -1.0, "netinccmn": -1.0})
    return pd.DataFrame(rows)


def _sp500() -> pd.DataFrame:
    current = [t for t in SP500_CORE if t not in DELISTED and t != REMOVED[0]] + [ADDED[0]]
    rows = [{"date": "2002-12-31", "action": "current", "ticker": t} for t in current]
    for ticker, day in DELISTED.items():
        if ticker in SP500_CORE:
            rows.append(
                {
                    "date": (day + pd.Timedelta(days=1)).date().isoformat(),
                    "action": "removed",
                    "ticker": ticker,
                }
            )
    rows.append({"date": REMOVED[1].date().isoformat(), "action": "removed", "ticker": REMOVED[0]})
    rows.append({"date": ADDED[1].date().isoformat(), "action": "added", "ticker": ADDED[0]})
    return pd.DataFrame(rows).assign(name="", contraticker="", contraname="", note="")


def _tickers() -> pd.DataFrame:
    sectors = ("Technology", "Energy", "Industrials")
    return pd.DataFrame(
        [
            {
                "table": "SF1",
                "ticker": t,
                "name": f"Synthetic {t}",
                "sector": sectors[i % 3],
                "currency": "USD",
                "isdelisted": "Y" if t in DELISTED else "N",
                "category": "Domestic Common Stock",
            }
            for i, t in enumerate(NAMES)
        ]
    )


def _actions() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": DELISTED[MERGED].date().isoformat(),
                "action": "acquisitionby",
                "ticker": MERGED,
                "name": "",
                "value": "",
                "contraticker": "Q01",
                "contraname": "",
            }
        ]
    )


def write_bundle(root: Path, *, seed: int = 7, with_hl: bool = True) -> Path:
    """Tiny zipped Sharadar-shaped bundle (``<table>.csv.zip``, sharadar.com direct)."""
    root.mkdir(parents=True, exist_ok=True)
    paths = _paths(np.random.default_rng(seed))
    tables = {
        "stocks": _stocks(paths, with_hl=with_hl),
        "fundamentals": _fundamentals(paths),
        "sp500": _sp500(),
        "tickers": _tickers(),
        "actions": _actions(),
    }
    for table, frame in tables.items():
        frame.to_csv(
            root / f"{table}.csv.zip",
            index=False,
            compression={"method": "zip", "archive_name": f"{table}.csv"},
        )
    return root


def _hsr_registration(path: Path) -> dict:
    reg = hsr.load_registration(path)
    reg["windows"] = {
        "development": {"first_entry": "2000-01-31", "last_entry": "2000-12-29"},
        "holdout": {"first_entry": "2001-01-31", "last_entry": "2002-06-28"},
    }
    reg["horizons_days"] = [30, 91]
    reg["primary"] = {**reg["primary"], "horizon_days": 30, "confirmation_horizon_days": 91}
    reg["screen_code_fingerprint"] = hsr.screen_code_fingerprint()
    if reg.get("universe_rule"):
        reg["universe_rule"] = {**reg["universe_rule"], "rank_from": 21, "rank_to": 36}
    return reg


def rehearsal_registration() -> dict:
    reg = json.loads((REPO / rehearsal.REGISTRATION_PATH).read_text())
    reg["windows"] = {
        "development": {"first_signal": "2000-01-01", "last_signal": "2000-12-31"},
        "confirmation": {
            "first_signal": "2001-01-01",
            "last_signal": "2002-06-30",
            "halves": ["2001-01-01/2001-09-30", "2001-10-01/2002-06-30"],
        },
        "classified_by": "signal_session",
    }
    reg["universes"]["sp400"] = {**reg["universes"]["sp400"], "rank_from": 21, "rank_to": 36}
    reg["regime_cuts"] = {
        "dev_cut": {
            "first_signal": "2000-01-01",
            "last_signal": "2000-06-30",
            "block": "development",
        },
        "conf_cut": {
            "first_signal": "2001-01-01",
            "last_signal": "2001-12-31",
            "block": "confirmation",
        },
    }
    reg["confirmation_family"] = {**reg["confirmation_family"], "resamples": 400}
    return reg


def make_repo(root: Path, *, signed: bool = True) -> Path:
    data = root / "docs" / "data"
    data.mkdir(parents=True)
    seal = json.loads((REPO / rehearsal.PARENT_SEAL).read_text())
    if not signed:
        seal = {"registration_id": seal["registration_id"], "signed": False}
    (data / "strategy_book_registration.json").write_text(json.dumps(seal))
    (data / rehearsal.REGISTRATION_PATH.name).write_text(json.dumps(rehearsal_registration()))
    return root


def build_dirs(sharadar: Path, out: Path) -> tuple[Path, Path]:
    """build-panel for both universes, then the baseline caches (no reveal)."""
    builds = {}
    for universe, source in (
        ("sp500", hsr.DEFAULT_REGISTRATION_PATH),
        ("midcap", hsr.MIDCAP_REGISTRATION_PATH),
    ):
        reg_path = out / f"{universe}_registration.json"
        reg_path.parent.mkdir(parents=True, exist_ok=True)
        reg_path.write_text(json.dumps(_hsr_registration(source)))
        target = out / f"hsr-{universe}"
        hsr.build_panel_files(sharadar, target, registration_path=reg_path)
        hsr.run_replay(
            target / "panel.csv.gz",
            target / "prices.csv.gz",
            terminal_path=target / "terminal_baseline.csv",
            registration_path=reg_path,
            store_path=out / f"{universe}_store.json",
        )
        builds[universe] = target
    return builds["sp500"], builds["midcap"]


@pytest.fixture(scope="module")
def licensed(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    root = tmp_path_factory.mktemp("owner-home")
    sharadar = write_bundle(root / "vendor")
    build, mid = build_dirs(sharadar, root / "builds")
    return {"root": root, "sharadar": sharadar, "build": build, "mid": mid}


def _read_episodes(scratch: Path, variant: str = "baseline") -> list[dict]:
    import gzip

    with gzip.open(scratch / f"episodes_{variant}.jsonl.gz", "rt") as handle:
        return [json.loads(line) for line in handle]


def test_develop_review_reveal_and_confirm_deleted(licensed: dict[str, Path], tmp_path: Path):
    repo = make_repo(tmp_path / "repo")
    out = rehearsal.develop(
        licensed["build"], licensed["mid"], licensed["sharadar"], repo_root=repo
    )
    store_path = repo / rehearsal.STORE_PATH
    text = store_path.read_text()
    store = json.loads(text)
    assert store["status"] == "development_committed"
    assert store["confirmation"] is None and store["reveal"] is None
    assert store["licensed_data"]["first_used_at"] and store["licensed_data"]["deleted_at"] is None
    assert store["labels"]["hl_basis_export"] == "high_low"
    assert store["family"]["coverage"] == pytest.approx(1 - 0.10 / 3)
    development = store["development"]
    assert development["interval_label"] == "development_descriptive"
    assert development["primary"]["interval"]["coverage"] == pytest.approx(0.90)
    assert development["primary"]["mature"] >= 5
    assert development["bench"]["deep_dip"]["verdict"] is None
    assert set(store["regime_cuts"]) == {"dev_cut"}
    assert [row["month"] for row in store["month_series"]][:2] == ["2000-01", "2000-02"]
    assert len(store["month_series"]) == 12
    assert store["delisting_sensitivity"]["development"]["haircut_non_merger"] == -0.3
    assert store["run_counts"]["overlap_excluded_from_sp400"] > 0
    # Nothing licensed in the committed file.
    for ticker in NAMES:
        assert ticker not in text
    assert "vendor" not in text and str(licensed["root"]) not in text
    assert rehearsal.privacy_violations(store, NAMES) == []

    scratch = out["scratch"]
    assert scratch.is_relative_to(licensed["build"] / rehearsal.SCRATCH_DIRNAME)
    episodes = _read_episodes(scratch)
    primary = [e for e in episodes if e["column"] == "primary" and e["mature"]]
    assert all(e["signal_session"] <= "2000-12-31" for e in episodes)
    assert development["counts"]["mature_episodes"] == len(primary)
    assert development["counts"]["by_market"].keys() <= {"sp500", "sp400"}

    with pytest.raises(rehearsal.RehearsalRefused, match="amendment"):
        rehearsal.develop(licensed["build"], licensed["mid"], licensed["sharadar"], repo_root=repo)

    findings = {row["title"]: row for row in rehearsal.findings(repo)}
    assert rehearsal.TITLE_DEVELOPMENT in findings
    assert findings[rehearsal.TITLE_DELETION_DUE]["severity"] == "warn"
    assert rehearsal.TITLE_REVEALED not in findings

    revealed = rehearsal.reveal(
        licensed["build"], licensed["mid"], licensed["sharadar"], repo_root=repo
    )["store"]
    confirmation = revealed["confirmation"]
    assert confirmation["development_reproduced"] is True
    assert confirmation["primary"]["interval"]["coverage"] == pytest.approx(1 - 0.10 / 3)
    assert confirmation["verdicts"]["primary"] in {
        "pass",
        "pass_delisting_sensitive",
        "fail_costs",
        "fail_excess",
        "inconclusive",
        "insufficient_episodes",
    }
    assert set(confirmation["verdicts"]["bench"]) == {"deep_dip", "revenue_growing"}
    assert [half["window"] for half in confirmation["bench"]["deep_dip"]["halves"]] == [
        "2001-01-01/2001-09-30",
        "2001-10-01/2002-06-30",
    ]
    assert revealed["reveal"]["evidence"] is True
    assert set(revealed["regime_cuts"]) == {"dev_cut", "conf_cut"}
    assert revealed["delisting_sensitivity"]["confirmation"]["verdict"]
    assert len(revealed["month_series"]) == 12 + 18
    assert revealed["development"] == store["development"]
    assert rehearsal.privacy_violations(revealed, NAMES) == []
    with pytest.raises(rehearsal.RehearsalRefused, match="already revealed"):
        rehearsal.reveal(licensed["build"], licensed["mid"], licensed["sharadar"], repo_root=repo)
    titles = {row["title"] for row in rehearsal.findings(repo)}
    assert rehearsal.TITLE_REVEALED in titles

    with pytest.raises(rehearsal.RehearsalRefused, match="still exist"):
        rehearsal.confirm_deleted(repo_root=repo, still_present=[licensed["sharadar"]])
    with pytest.raises(rehearsal.RehearsalRefused, match="confirm-deleted"):
        rehearsal.confirm_deleted(repo_root=repo)
    stamp = "2026-12-01T10:00:00+00:00"
    (repo / hsr.DEFAULT_STORE_PATH).write_text(json.dumps({"licensed_data": {"deleted_at": stamp}}))
    assert rehearsal.confirm_deleted(repo_root=repo)["deleted_at"] == stamp
    titles = {row["title"] for row in rehearsal.findings(repo)}
    assert rehearsal.TITLE_DELETION_DUE not in titles
    assert rehearsal.status(repo)["licensed_data"]["deleted_at"] == stamp


def _blocks(store: dict) -> str:
    keep = {
        key: store[key]
        for key in (
            "development",
            "confirmation",
            "delisting_sensitivity",
            "regime_cuts",
            "month_series",
            "run_counts",
        )
    }
    for block in ("development", "confirmation"):
        keep[block] = {k: v for k, v in keep[block].items() if k != "computed_at"}
    return json.dumps(keep, sort_keys=True)


def _scratch_rows(scratch: Path, variant: str) -> list[str]:
    return sorted(json.dumps(row, sort_keys=True) for row in _read_episodes(scratch, variant))


def test_blocks_do_not_depend_on_the_batch_size(licensed: dict[str, Path], tmp_path: Path):
    stores, scratches = [], []
    for size in (10_000, 50, 3):
        repo = make_repo(tmp_path / f"repo-{size}")
        scratch = tmp_path / f"scratch-{size}"
        paths = (licensed["build"], licensed["mid"], licensed["sharadar"])
        rehearsal.develop(*paths, repo_root=repo, scratch=scratch, batch_size=size)
        out = rehearsal.reveal(*paths, repo_root=repo, scratch=scratch, batch_size=size)
        stores.append(_blocks(out["store"]))
        scratches.append(out["scratch"])
        assert not list(scratch.glob(f"{tape.TAPE_SPLIT_PREFIX}*"))
    assert stores[0] == stores[1] == stores[2]
    assert json.loads(stores[0])["confirmation"]["primary"]["mature"] >= 5
    for variant in (rehearsal.BASELINE, rehearsal.SENSITIVITY):
        rows = [_scratch_rows(scratch, variant) for scratch in scratches]
        assert rows[0] == rows[1] == rows[2]


def test_batched_walk_equals_the_whole_book_walk(licensed: dict[str, Path], tmp_path: Path):
    registration = rehearsal_registration()
    last = registration["windows"]["confirmation"]["last_signal"]
    builds = (
        tape.BuildDir(licensed["build"], "sp500"),
        tape.BuildDir(licensed["mid"], "midcap"),
        licensed["sharadar"],
        registration,
    )
    inputs = tape.build_inputs(*builds)
    source = tape.prepare(
        *builds,
        work_dir=tmp_path / "work",
        batch_size=4,
        cross_options=rehearsal.walk_options(registration, last),
    )
    try:
        assert len(source.batches) > 3
        batched = rehearsal.walk_batches(source, registration, last_signal=last, target=tmp_path)
    finally:
        source.remove()
    for variant in (rehearsal.BASELINE, rehearsal.SENSITIVITY):
        whole = rehearsal.walk(inputs, registration, last_signal=last, variant=variant)
        expected = [rehearsal._compact(e) for e in whole["episodes"]]
        if variant == rehearsal.SENSITIVITY:
            expected = [e for e in expected if e["column"] == "primary"]
        got = batched[variant]
        assert json.dumps(got["episodes"], default=str) == json.dumps(expected, default=str)
        assert got["counts"] == whole["counts"]
        assert got["cap_would_block_days"] == whole["cap_would_block_days"]
        assert got["scoring_date"] == whole["scoring_date"]
        events = [e for e in whole["events"] if e["kind"] == "no_next_bar"]
        assert len(got["events"]) == sum(1 for e in events if e["column"] == "primary")
    assert source.names_walked == len(inputs.specs)
    assert source.counts == inputs.counts


def test_memory_warning_suggests_a_smaller_batch(monkeypatch: pytest.MonkeyPatch):
    class _Memory:
        available = 2_500 * 2**20

    class _Psutil:
        @staticmethod
        def virtual_memory():
            return _Memory()

    monkeypatch.setitem(sys.modules, "psutil", _Psutil)
    assert rehearsal.memory_warning(4_450, 6_500, 10) is None
    warning = rehearsal.memory_warning(4_450, 6_500, 4_450)
    assert warning and "--batch-size" in warning and "smaller" in warning
    suggested = int(warning.rsplit("for example ", 1)[1].rstrip(").").split()[0])
    assert suggested < 4_450
    assert rehearsal.memory_estimate_mb(4_450, 6_500, suggested) <= 2_500 or suggested == 25


def test_cli_batch_size_is_passed_through(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    seen = {}

    def _develop(*args, **kwargs):
        seen.update(kwargs)
        return {"store": {"development": {"primary": {}}}, "scratch": tmp_path}

    monkeypatch.setattr(rehearsal, "develop", _develop)
    paths = ["--build", "b", "--mid-build", "m", "--sharadar-dir", "s"]
    assert rehearsal.main(["develop", *paths, "--batch-size", "75"]) == 0
    assert seen["batch_size"] == 75
    assert rehearsal.main(["develop", *paths]) == 0
    assert seen["batch_size"] == tape.DEFAULT_BATCH_SIZE
    with pytest.raises(SystemExit):
        rehearsal.main(["develop", *paths, "--batch-size", "0"])
    capsys.readouterr()


def test_reveal_needs_a_development_block(licensed: dict[str, Path], tmp_path: Path):
    repo = make_repo(tmp_path / "repo")
    with pytest.raises(rehearsal.RehearsalRefused, match="No development block"):
        rehearsal.reveal(licensed["build"], licensed["mid"], licensed["sharadar"], repo_root=repo)


def test_refuses_unsigned_parent_missing_registration_and_paths_in_the_repo(
    licensed: dict[str, Path], tmp_path: Path
):
    unsigned = make_repo(tmp_path / "unsigned", signed=False)
    with pytest.raises(RegistrationUnsigned):
        rehearsal.develop(
            licensed["build"], licensed["mid"], licensed["sharadar"], repo_root=unsigned
        )
    repo = make_repo(tmp_path / "repo")
    inside = repo / "builds" / "hsr"
    inside.mkdir(parents=True)
    for kwargs in (
        {"build": inside},
        {"mid_build": inside},
        {"sharadar_dir": inside},
        {"scratch": inside},
    ):
        args = {
            "build": licensed["build"],
            "mid_build": licensed["mid"],
            "sharadar_dir": licensed["sharadar"],
            **kwargs,
        }
        with pytest.raises(rehearsal.RehearsalRefused, match="inside the repository"):
            rehearsal.develop(repo_root=repo, **args)
    (repo / rehearsal.REGISTRATION_PATH).unlink()
    with pytest.raises(rehearsal.RehearsalRefused, match="not registered"):
        rehearsal.develop(licensed["build"], licensed["mid"], licensed["sharadar"], repo_root=repo)
    assert not (repo / rehearsal.STORE_PATH).exists()


def test_a_missing_or_stale_cache_names_the_build_command(
    licensed: dict[str, Path], tmp_path: Path
):
    copy = tmp_path / "copy"
    shutil.copytree(licensed["build"], copy, ignore=shutil.ignore_patterns("signals_cache*"))
    with pytest.raises(tape.InputsMissing) as missing:
        tape.checked_cache(tape.BuildDir(copy, "sp500"))
    message = str(missing.value)
    assert f"ftse-historical-replay run --panel {copy / 'panel.csv.gz'}" in message
    assert "--reveal-holdout" in message and "without --reveal-holdout" in message
    assert "git restore docs/data/historical_screen_replay.json" in message
    assert "--reveal-holdout\n" not in message and "run --reveal" not in message

    stale = tmp_path / "stale"
    shutil.copytree(licensed["mid"], stale)
    key = json.loads((stale / "signals_cache.csv.gz.key.json").read_text())
    (stale / "signals_cache.csv.gz.key.json").write_text(json.dumps({**key, "panel": "x"}))
    with pytest.raises(tape.InputsMissing, match="different panel") as old:
        tape.checked_cache(tape.BuildDir(stale, "midcap"))
    assert "--universe midcap" in str(old.value)
    assert "historical_screen_replay_midcap.json" in str(old.value)


def test_sp400_is_carried_cap_rank_minus_that_sessions_sp500(licensed: dict[str, Path]):
    days = [
        date(2000, 1, 28),
        date(2000, 1, 31),
        date(2000, 2, 1),
        date(2000, 2, 29),
        date(2000, 3, 1),
    ]
    month_sets = {date(2000, 1, 31): {"M1", "M2", "BIG"}, date(2000, 2, 29): {"M2", "M3"}}
    sp500 = [set(), {"BIG"}, {"BIG"}, {"M3"}, set()]
    members, overlap = tape.sp400_members_by_day(month_sets, days, sp500)
    assert members == [set(), {"M1", "M2"}, {"M1", "M2"}, {"M2"}, {"M2", "M3"}]
    assert overlap == 3
    spans = tape.spans_from_days(days, members)
    assert spans["M2"] == [(days[1], days[4])]
    assert spans["M3"] == [(days[4], days[4])]

    reg = rehearsal_registration()
    inputs = tape.build_inputs(
        tape.BuildDir(licensed["build"], "sp500"),
        tape.BuildDir(licensed["mid"], "midcap"),
        licensed["sharadar"],
        reg,
    )
    by_market: dict[str, dict[str, list]] = {"sp500": {}, "sp400": {}}
    for spec in inputs.specs:
        by_market[spec.market][spec.ticker] = spec.universe
        assert spec.book_key == spec.ticker
    for ticker, mid_spans in by_market["sp400"].items():
        big = by_market["sp500"].get(ticker) or []
        for a, b in mid_spans:
            for c, d in big:
                assert b < c or d < a, ticker
    assert set(inputs.haircuts) == set(DELISTED) & set(inputs.tickers)
    if MERGED in inputs.haircuts:
        assert inputs.haircuts[MERGED] == {"baseline": 0.0, "sensitivity": 0.0}
    assert inputs.haircuts["Q05"] == {"baseline": 0.0, "sensitivity": -0.3}


def test_hl_basis_comes_from_the_export_header(tmp_path: Path):
    with_hl = tmp_path / "stocks.csv.zip"
    frame = pd.DataFrame(
        {"ticker": ["A"], "date": ["2000-01-03"], "high": [2.0], "low": [1.0], "close": [1.5]}
    )
    frame.to_csv(with_hl, index=False, compression={"method": "zip", "archive_name": "stocks.csv"})
    assert tape.export_hl_basis(with_hl) == tape.HL_HIGH_LOW
    without = tmp_path / "stocks2.csv"
    frame.drop(columns=["low"]).to_csv(without, index=False)
    assert tape.export_hl_basis(without) == tape.HL_CLOSES
    daily = tmp_path / "daily.csv.gz"
    frame.assign(open=1.5).to_csv(daily, index=False)
    assert tape.load_tapes([daily], {"A"}, hl_basis=tape.HL_CLOSES)["A"].highs is None
    assert tape.load_tapes([daily], {"A"}, hl_basis=tape.HL_HIGH_LOW)["A"].highs == [2.0]


def _statements(rows: list[tuple]) -> pd.DataFrame:
    frame = pd.DataFrame(
        rows,
        columns=["dimension", "filed", "cal", "revenue", "opinc", "ebit", "epsdil", "eps", "fcf"],
    )
    frame["filed"] = [date.fromisoformat(v).toordinal() for v in frame["filed"]]
    frame["cal"] = [date.fromisoformat(v).toordinal() for v in frame["cal"]]
    return frame.assign(ticker="Z")


def _verdicts(frame: pd.DataFrame, sessions: list[str]) -> list[str]:
    ords = np.array([date.fromisoformat(s).toordinal() for s in sessions])
    codes, _index, _details = tape.decline_codes(frame, ords, tape.DeclineRules())
    return [tape.GATE_LABELS[int(code)] for code in codes]


def test_decline_gate_reads_art_ttm_with_the_filing_lag():
    rows = [
        ("ART", "1999-02-10", "1998-12-31", 100.0, 10.0, 11.0, 1.0, 1.0, 5.0),
        ("ART", "2000-02-10", "1999-12-31", 103.0, 10.5, 11.0, 1.0, 1.0, 5.0),
        ("ART", "2001-02-10", "2000-12-31", 90.0, 9.0, 10.0, 1.0, 1.0, 5.0),
    ]
    frame = _statements(rows)
    # Filed 10 Feb: invisible on the 11th (one day), visible on the 12th (two days).
    assert _verdicts(frame, ["2000-02-11", "2000-02-12", "2001-02-11", "2001-02-12"]) == [
        "insufficient_data",
        "clear",
        "clear",
        "declining",
    ]
    # 456 days after the last filing it is stale.
    assert _verdicts(frame, ["2002-05-12", "2002-05-13"]) == ["declining", "insufficient_data"]
    _codes, _index, details = tape.decline_codes(
        frame, np.array([date(2001, 2, 12).toordinal()]), tape.DeclineRules()
    )
    checks, soft = details[0]
    assert checks["hard_reasons"] == ["revenue_decline"]
    assert checks["revenue"]["change_pct"] == pytest.approx(90 / 103 - 1)
    assert checks["operating_margin"]["pair"] == "opinc/revenue"


def test_two_soft_reasons_decline_and_interim_revenue_is_hard():
    soft = _statements(
        [
            ("ART", "1999-02-10", "1998-12-31", 100.0, 10.0, 11.0, 1.0, 1.0, 10.0),
            ("ART", "2000-02-10", "1999-12-31", 101.0, 10.1, 11.0, 0.7, 0.7, 4.0),
        ]
    )
    assert _verdicts(soft, ["2000-03-01"]) == ["declining"]
    one_soft = _statements(
        [
            ("ART", "1999-02-10", "1998-12-31", 100.0, 10.0, 11.0, 1.0, 1.0, 10.0),
            ("ART", "2000-02-10", "1999-12-31", 101.0, 10.1, 11.0, 0.7, 0.7, 9.0),
        ]
    )
    assert _verdicts(one_soft, ["2000-03-01"]) == ["clear"]
    interim = _statements(
        [
            ("ART", "1999-02-10", "1998-12-31", 100.0, 10.0, 11.0, 1.0, 1.0, 10.0),
            ("ART", "2000-02-10", "1999-12-31", 101.0, 10.1, 11.0, 1.0, 1.0, 10.0),
            ("ARQ", "1999-05-10", "1999-03-31", 25.0, None, None, 0.25, 0.25, None),
            ("ARQ", "2000-05-10", "2000-03-31", 22.0, None, None, 0.25, 0.25, None),
        ]
    )
    assert _verdicts(interim, ["2000-05-11", "2000-05-12"]) == ["clear", "declining"]


def test_price_only_sector_breadth_needs_coverage():
    days = [date(2000, 1, 3) + pd.Timedelta(days=i).to_pytimedelta() for i in range(260)]
    falling = [100.0 * 0.995**i for i in range(260)]
    rising = [100.0 * 1.002**i for i in range(260)]
    downloads = {
        f"F{i}": sbo.Download(as_of=days[-1], sessions=days, closes=falling) for i in range(5)
    }
    downloads.update(
        {f"R{i}": sbo.Download(as_of=days[-1], sessions=days, closes=rising) for i in range(5)}
    )
    sectors = {**{f"F{i}": "Energy" for i in range(5)}, **{f"R{i}": "Tech" for i in range(5)}}
    sectors["F9"] = "Energy"
    members = [set(downloads) for _ in days]
    found = tape.sector_tapes(days, members, sectors, downloads, tape.SectorRules())
    labels = tape.GATE_LABELS
    assert labels[found["Energy"].codes[-1]] == "headwind"
    assert labels[found["Tech"].codes[-1]] == "sound"
    assert labels[found["Energy"].codes[150]] == "insufficient_data"
    inputs = found["Energy"].inputs(len(days) - 1)
    assert inputs["breadth_members"] == 5 and inputs["breadth_share"] == 1.0
    thin = [set(list(downloads)[:3]) for _ in days]
    assert (
        labels[
            tape.sector_tapes(days, thin, sectors, downloads, tape.SectorRules())["Energy"].codes[
                -1
            ]
        ]
        == "insufficient_data"
    )
    # A member without data lowers coverage below 60%.
    members_gap = [set(downloads) | {"F9", "X1", "X2", "X3"} for _ in days]
    sectors.update({"X1": "Energy", "X2": "Energy", "X3": "Energy"})
    gap = tape.sector_tapes(days, members_gap, sectors, downloads, tape.SectorRules())
    assert labels[gap["Energy"].codes[-1]] == "insufficient_data"


def test_week_bootstrap_matches_brute_force():
    rng = np.random.default_rng(3)
    values = rng.normal(0.01, 0.05, 37).tolist()
    weeks = rng.integers(0, 9, 37)
    _labels, week_ids = np.unique(weeks, return_inverse=True)
    count = int(week_ids.max()) + 1
    got = rehearsal.bootstrap_median(values, week_ids, count, resamples=50, seed=11)
    draw = np.random.default_rng(11).integers(0, count, size=(50, count))
    by_week = [np.asarray(values)[week_ids == w] for w in range(count)]
    expected = [np.median(np.concatenate([by_week[w] for w in row])) for row in draw]
    assert got == pytest.approx(expected)
    kept = (rng.random(37) < 0.4).tolist()
    diff = rehearsal.bootstrap_mean_difference(values, kept, week_ids, count, resamples=50, seed=11)
    kept_np = np.asarray(kept)
    brute = []
    for row in draw:
        sample = np.concatenate([np.flatnonzero(week_ids == w) for w in row])
        vals = np.asarray(values)[sample]
        k = kept_np[sample]
        brute.append(vals[k].mean() - vals.mean() if k.any() else np.nan)
    assert np.allclose(diff, brute, equal_nan=True)


def test_bonferroni_interval_and_verdicts():
    fam = rehearsal.family(rehearsal_registration())
    assert fam["m"] == 3 and fam["coverage"] == pytest.approx(0.9666666667)
    samples = np.arange(1, 10001, dtype=float)
    bounds = rehearsal.interval(samples, fam["coverage"])
    assert bounds["low"] == pytest.approx(np.percentile(samples, 100 * 0.1 / 6))
    assert bounds["high"] == pytest.approx(np.percentile(samples, 100 * (1 - 0.1 / 6)))
    verdict = rehearsal.primary_verdict
    assert verdict(0.02, {"low": 0.01, "high": 0.03}, 40) == "pass"
    assert verdict(-0.01, {"low": 0.01, "high": 0.03}, 40) == "fail_costs"
    assert verdict(0.02, {"low": -0.03, "high": -0.01}, 40) == "fail_excess"
    assert verdict(0.02, {"low": -0.01, "high": 0.03}, 40) == "inconclusive"
    assert verdict(0.02, {"low": 0.01, "high": 0.03}, 4) == "insufficient_episodes"
    candidate = rehearsal.candidate_verdict
    assert candidate({"interval": {"low": 0.01, "high": 0.02}}, [0.1, 0.2]) == "pass"
    assert candidate({"interval": {"low": 0.01, "high": 0.02}}, [0.1, -0.2]) == "inconclusive"
    assert candidate({"interval": {"low": -0.02, "high": -0.01}}, [0.1, 0.2]) == "fail"


def test_cells_under_five_publish_only_the_count():
    block = {
        "mature": 4,
        "fair_cost_median": 0.12,
        "launch_share": 0.5,
        "interval": {"coverage": 0.9, "low": 0.01, "high": 0.2},
        "nested": {"count": 9, "median_fair_cost": 0.3},
    }
    out = rehearsal.suppress_small(block)
    assert out["mature"] == 4 and out["fair_cost_median"] is None and out["launch_share"] is None
    assert out["interval"] == {"coverage": 0.9, "low": None, "high": None}
    assert out["nested"]["median_fair_cost"] == 0.3
    assert rehearsal.privacy_violations(block)  # unsuppressed small cell is refused
    assert rehearsal.privacy_violations(out, secrets=()) == []
    episodes = [
        {
            "column": "primary",
            "mature": True,
            "signal_session": "2000-01-04",
            "decision_return_floor": 0.1,
        }
    ] * 4
    series = rehearsal.month_series(episodes, ("2000-01-01", "2000-02-29"))
    assert series == [{"month": "2000-01", "episodes": 4}, {"month": "2000-02", "episodes": 0}]


@pytest.mark.parametrize(
    "payload, reason",
    [
        ({"rows": {"count": 9}}, "forbidden key"),
        ({"block": {"ticker": "x"}}, "forbidden key"),
        ({"best": "Q07"}, "universe ticker"),
        ({"episode": "sp500:Q07:primary:2001-01-02"}, "universe ticker"),
        ({"Q07": 1}, "universe ticker"),
        ({"close": 101.5}, "per-name"),
        ({"market_cap": 3.1e9}, "per-name"),
        ({"fair_cost_return": [0.1, 0.2]}, "per-name"),
        ({"pass__graham": True}, "signal-cache column"),
        ({"cell": {"count": 3, "median_fair_cost": 0.04}}, "under 5"),
        ({"cell": {"n": 2, "interval": {"low": 0.1, "high": 0.2}}}, "under 5"),
        ({"note": "/home/owner/builds/hsr"}, "home-directory"),
        ({"note": "~/hsr-build"}, "home-directory"),
        ({"note": "read from the Sharadar bundle"}, "vendor directory"),
        ({"note": "key abc123SECRETxyz used"}, "API key"),
    ],
)
def test_privacy_guard_refuses_licensed_content(
    payload: dict, reason: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("SHARADAR_API_KEY", "abc123SECRETxyz")
    problems = rehearsal.privacy_violations(
        payload, ["Q07", "Q08"], home="/home/owner", secrets=["abc123SECRETxyz"]
    )
    assert any(reason in problem for problem in problems), problems
    repo = tmp_path / "repo"
    with pytest.raises(rehearsal.PrivacyViolation):
        rehearsal.write_store(repo / rehearsal.STORE_PATH, payload, ["Q07"])
    assert not (repo / rehearsal.STORE_PATH).exists()


@pytest.mark.parametrize(
    "note",
    [
        r"C:\Users\jamie\hsr-build\panel.csv.gz",
        "C:/Users/jamie/hsr-build",
        "/c/Users/jamie/hsr-build",
        r"built in D:\Users\someone\scratch",
    ],
)
def test_privacy_guard_refuses_windows_home_paths(note: str):
    for home in (r"C:\Users\jamie", "/home/owner"):
        problems = rehearsal.privacy_violations({"note": note}, [], home=home, secrets=[])
        assert any("home-directory" in problem for problem in problems), (note, home)


def test_privacy_guard_allows_plain_dates_and_ratios():
    payload = {"window": "2000-01/2012-12", "share": "3/5", "note": "users/home split"}
    assert rehearsal.privacy_violations(payload, [], home=r"C:\Users\jamie", secrets=[]) == []


def test_privacy_guard_reads_api_keys_from_the_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SHARADAR_API_KEY", "zz-not-a-real-key-123")
    assert rehearsal.privacy_violations({"x": "zz-not-a-real-key-123"})
    assert rehearsal.privacy_violations({"x": "fine", "episodes": 12, "month": "2000-01"}) == []


def test_cli_status_and_help(capsys: pytest.CaptureFixture[str]):
    assert rehearsal.main(["status"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["registration_id"] == "strategy-book-us-rehearsal-v0"
    assert status["parent_signed"] is True
    for command in ("develop", "reveal", "confirm-deleted"):
        with pytest.raises(SystemExit):
            rehearsal.main([command, "--help"])
        assert "usage: ftse-strategy-book-rehearsal" in capsys.readouterr().out


def test_cli_refuses_without_writing(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    code = rehearsal.main(
        [
            "develop",
            "--build",
            str(REPO / "docs"),
            "--mid-build",
            str(tmp_path),
            "--sharadar-dir",
            str(tmp_path),
        ]
    )
    assert code == 2
    assert "inside the repository" in capsys.readouterr().err
    assert not (REPO / rehearsal.STORE_PATH).exists()
