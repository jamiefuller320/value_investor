"""Memo model comparison: selection, frozen inputs, scoring, judge, calibration, decision, ops."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

import value_investor.memo_model_comparison as mmc
from value_investor.ops_monitor import check_memo_model_comparison
from value_investor.research import agent as research_agent

NOW = datetime(2026, 11, 10, 11, 0, tzinfo=UTC)
BODY = (
    "Group revenue rose to £1,234.5m in the year ended 31 March 2026. "
    "The Board recommends a final dividend of 12.3p per share. Net debt was £410m."
)


def _cand(ticker: str, **kw: Any) -> mmc.Candidate:
    base = dict(
        market="sp500",
        ticker=ticker,
        name=ticker,
        signal="buy",
        session="2026-11-09",
        decline="clear",
        sector="sound",
        price_entry=False,
        alternative_entry=False,
        rsi=40.0,
        filings_with_body=10,
        adjusted_signal="buy",
        screen_verdict="neutral",
    )
    base.update(kw)
    return mmc.Candidate(**base)


def _raw(verdict: str = "accumulate", *, good: bool = True) -> str:
    quote = (
        "The Board recommends a final dividend of 12.3p per share" if good else "Revenue tripled"
    )
    return f"""RESEARCH VERDICT
Verdict: {verdict}
Risk: medium
Confidence: 0.70
Rationale: Filings support the buy case.
RiskTags: cyclical

EVIDENCE
- [filings/bodies/annual.txt] "{quote}" — dividend maintained
- [filings/bodies/annual.txt] "Net debt was £410m" — leverage modest
- [filings/bodies/missing.txt] "anything" — bad path

NUMBERS
- Revenue | £1,234.5m | FY2026 | [filings/bodies/annual.txt]
- Margin | 99.9% | FY2026 | [filings/bodies/annual.txt]

THESIS BREAKS
- A dividend cut in the next interim.
- Net debt above £600m.
"""


def _sources(tmp_path: Path) -> Path:
    src = tmp_path / "src_sources"
    (src / "filings" / "bodies").mkdir(parents=True)
    (src / "filings" / "bodies" / "annual.txt").write_text(BODY, encoding="utf-8")
    (src / "screening_snapshot.json").write_text("{}", encoding="utf-8")
    return src


def _manifest(names: int = 2, *, amend: bool = True, tmp: Path | None = None) -> dict[str, Any]:
    entries = []
    for idx in range(names):
        ticker = f"T{idx}"
        entries.append(
            {
                "slug": f"sp500__{ticker}",
                "market": "sp500",
                "ticker": ticker,
                "name": f"Name {idx}",
                "bucket": "near_entry" if idx else "gate_flagged",
                "signal": "buy",
                "session": "2026-11-09",
                "decline_verdict": "clear",
                "sector_verdict": "sound",
                "price_entry": True,
                "alternative_entry": True,
                "rsi_14": 30.0,
                "filings_with_body": 1,
            }
        )
    manifest = {
        "schema_version": 1,
        "comparison_id": "test-comparison",
        "names": entries,
        "models": {"incumbent": mmc.INCUMBENT_MODEL, "challenger": mmc.CHALLENGER_MODEL},
        "budget": {"estimated_total_usd": 2.88, "cap_usd": mmc.BUDGET_CAP_USD},
    }
    if amend:
        manifest = mmc.amend_rule_v2(manifest, store=tmp or Path("/nonexistent-store"))
    return manifest


class FakeRunner:
    def __init__(
        self, verdicts: dict[str, str] | None = None, fail: set[str] | None = None
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self.verdicts = verdicts or {}
        self.fail = fail or set()

    def __call__(self, **kw: Any) -> Any:
        self.calls.append(kw)
        model = kw["model"]
        if model in self.fail:
            raise RuntimeError("model down")
        verdict = self.verdicts.get(model, "accumulate")
        kw["capture"].update(
            {
                "raw_text": _raw(verdict, good=model == mmc.CHALLENGER_MODEL),
                "prompt": "prompt",
                "latency_seconds": 12.0,
                "usage": {
                    "charged_cents": 50.0,
                    "input_tokens": 1000,
                    "output_tokens": 200,
                    "total_tokens": 1200,
                },
            }
        )
        return SimpleNamespace(
            research_verdict=verdict,
            research_risk_level="medium",
            research_confidence=0.7,
            research_rationale="Filings support the buy case.",
            risk_tags=["cyclical"],
        )


def _make_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, names: int) -> Path:
    root = tmp_path / "repo"
    store = mmc.store_dir(root)
    store.mkdir(parents=True)
    (store / "manifest.json").write_text(json.dumps(_manifest(names)), encoding="utf-8")
    sources = _sources(tmp_path)
    monkeypatch.setattr(mmc, "_sources_for", lambda entry, _root: sources)
    monkeypatch.setattr(
        mmc, "_report_for", lambda entry, _root: SimpleNamespace(ticker=entry["ticker"])
    )
    return root


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return _make_repo(tmp_path, monkeypatch, 2)


@pytest.fixture
def repo6(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return _make_repo(tmp_path, monkeypatch, 6)


def _generate(
    root: Path,
    runner: FakeRunner,
    *,
    remaining: float = 100.0,
    spent: list[float] | None = None,
    models: list[str] | None = None,
    now: datetime = NOW,
) -> dict[str, Any]:
    ledger = spent if spent is not None else []
    return mmc.run_generation(
        root,
        now=now,
        api_key="k",
        runner=runner,
        list_models=lambda: (
            models
            if models is not None
            else [mmc.INCUMBENT_MODEL, mmc.CHALLENGER_MODEL, "grok-4.7"]
        ),
        budget_status=lambda: {"remaining_weekly_ops_usd": remaining},
        record_spend=ledger.append,
    )


def test_challenger_is_strongest_configured_grok() -> None:
    assert mmc.CHALLENGER_MODEL == "grok-4.6"
    assert (
        mmc.strongest_configured_grok({"grok-4.5": 1, "grok-4.10": 1, "grok-4.6": 1}) == "grok-4.10"
    )
    assert mmc.estimated_memo_usd(mmc.INCUMBENT_MODEL) == 0.40
    assert mmc.estimated_memo_usd("grok-4.6") == 1.04
    assert mmc.estimated_total_usd(12, ("composer-2.5", "grok-4.6")) == 17.28 <= mmc.BUDGET_CAP_USD


def test_pick_market_prefers_adverse_contrast_and_entry_order() -> None:
    pool = [
        _cand("CLEAN_HI", rsi=45.0),
        _cand("CLEAN_ALT", alternative_entry=True, rsi=38.0),
        _cand("CLEAN_PRI", price_entry=True, alternative_entry=True, rsi=30.0),
        _cand("INSUFF", sector="insufficient_data", price_entry=True, rsi=20.0),
        _cand("DECL", decline="declining", rsi=44.0),
    ]
    picked = [(c.ticker, bucket) for c, bucket in mmc.pick_market(pool, 3)]
    assert picked == [
        ("CLEAN_PRI", "near_entry"),
        ("CLEAN_ALT", "near_entry"),
        ("DECL", "gate_flagged"),
    ]
    # Too few clean names: flagged names fill the rest.
    short = [
        (c.ticker, b)
        for c, b in mmc.pick_market(
            [_cand("A"), _cand("D", decline="declining"), _cand("H", sector="headwind")], 3
        )
    ]
    assert [t for t, _ in short] == ["A", "D", "H"]


def test_score_memo_checks_quotes_numbers_and_flags(tmp_path: Path) -> None:
    src = _sources(tmp_path)
    scored = mmc.score_memo(
        _raw(good=True) + "\nGuidance to 2030.", sources_dir=src, as_of=date(2026, 11, 10)
    )
    assert scored["evidence_count"] == 3
    assert scored["evidence_filing_body"] == 2
    assert scored["quotes_found"] == 2
    assert scored["numbers_found"] == 1
    assert scored["hallucination_flags"]["unresolved_path"] == 1
    assert scored["hallucination_flags"]["number_not_found"] == 1
    assert scored["hallucination_flag_total"] == 2
    assert scored["thesis_breaks"] == [
        "A dividend cut in the next interim.",
        "Net debt above £600m.",
    ]
    assert scored["future_year_mentions"] == [2030]
    bad = mmc.score_memo(_raw(good=False), sources_dir=src, as_of=date(2026, 11, 10))
    assert bad["hallucination_flags"]["quote_not_found"] == 1
    # Absolute paths into the sources folder resolve; traversal does not.
    assert mmc._resolve(src, f"{src.resolve()}/filings/bodies/annual.txt") is not None
    assert mmc._resolve(src, "../../etc/passwd") is None


def test_book_effect_uses_core_sell_reason() -> None:
    assert mmc.book_effect("pass", "buy") == "blocks"
    assert mmc.book_effect("caution", "buy") == "allows"
    assert mmc.book_effect(None, "buy") == "missing"


def test_generation_writes_only_the_comparison_store_and_blinds(repo: Path) -> None:
    runner = FakeRunner(verdicts={mmc.CHALLENGER_MODEL: "pass"})
    spent: list[float] = []
    status = _generate(repo, runner, spent=spent)
    store = mmc.store_dir(repo)
    assert status["state"] == mmc.STATE_GENERATED
    assert status["complete_pairs"] == 2
    assert len(runner.calls) == 4
    assert sorted(spent) == [0.40, 0.40, 1.04, 1.04]
    assert status["spend"]["estimated_usd"] == pytest.approx(2.88)
    assert status["runtime_models"]["grok_ids"] == ["grok-4.6", "grok-4.7"]
    # Same frozen inputs and as-of date for both models of a name.
    first = [c for c in runner.calls if c["report"].ticker == "T0"]
    assert first[0]["sources_dir"] == first[1]["sources_dir"]
    assert first[0]["as_of_date"] == first[1]["as_of_date"] == "2026-11-10"
    assert {c["model"] for c in first} == {mmc.INCUMBENT_MODEL, mmc.CHALLENGER_MODEL}
    # Nothing outside the comparison store and its scratch folder.
    assert sorted(p.name for p in (repo / "docs" / "data").iterdir()) == ["memo_model_comparison"]
    key = json.loads((store / "blind_key.json").read_text())
    assert set(key["names"]) == {"sp500__T0", "sp500__T1"}
    memo_a = (store / "memos" / "sp500__T0" / "A.json").read_text()
    assert mmc.INCUMBENT_MODEL not in memo_a and mmc.CHALLENGER_MODEL not in memo_a
    assert "charged" not in memo_a and "latency" not in memo_a
    # Under rule v2 the owner review is written by the judge step, not generation.
    assert not (store / "review.md").exists()
    assert not (store / "ratings_template.json").exists()
    assert mmc.due_for_judge(repo) is True
    results = json.loads((store / "results.json").read_text())
    assert results["verdict_agreement"] == {"agree": 0, "of": 2, "share": 0.0}
    assert results["book_effect_agreement"]["agree"] == 0
    assert results["by_model"][mmc.CHALLENGER_MODEL]["blocks"] == 2
    assert results["by_model"][mmc.CHALLENGER_MODEL]["charged_usd_per_memo"] == 0.5
    assert not (store / "ratings.json").exists()
    assert mmc.due_for_generation(repo) is False
    # Rerun is a no-op once ready.
    _generate(repo, runner)
    assert len(runner.calls) == 4


def test_unavailable_model_fails_closed(repo: Path) -> None:
    runner = FakeRunner()
    status = _generate(repo, runner, models=[mmc.INCUMBENT_MODEL])
    assert runner.calls == []
    assert "grok-4.6" in status["errors"][0]
    titles = [f["title"] for f in mmc.findings(repo, NOW)]
    assert titles == [mmc.TITLE_FAILED]


def test_weekly_headroom_stop_is_retryable_but_cap_is_final(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner()
    status = _generate(repo, runner, remaining=mmc.STRATEGY_BOOK_RESERVE_USD + 0.2)
    assert runner.calls == []
    assert status["budget_stop"]["kind"] == "weekly_headroom"
    assert mmc.due_for_generation(repo) is True
    monkeypatch.setattr(mmc, "BUDGET_CAP_USD", 1.0)
    status = _generate(repo, runner)
    assert len(runner.calls) == 1
    assert status["budget_stop"]["kind"] == "cap"
    assert status["state"] == mmc.STATE_INCOMPLETE
    assert mmc.due_for_generation(repo) is False


def test_failed_memo_retries_once_then_exhausts(repo: Path) -> None:
    runner = FakeRunner(fail={mmc.CHALLENGER_MODEL})
    first = _generate(repo, runner)
    assert first["state"] == mmc.STATE_INCOMPLETE
    assert any("model down" in e for e in first["errors"])
    second = _generate(repo, runner)
    assert second["exhausted_pairs"] == ["sp500__T0", "sp500__T1"]
    third_calls = len(runner.calls)
    _generate(repo, runner)
    assert len(runner.calls) == third_calls


def test_changed_inputs_regenerate_both_memos(repo: Path, tmp_path: Path) -> None:
    runner = FakeRunner(fail={mmc.CHALLENGER_MODEL})
    _generate(repo, runner)
    before = len(runner.calls)
    (tmp_path / "src_sources" / "filings" / "bodies" / "new.txt").write_text(
        "new filing", encoding="utf-8"
    )
    runner.fail = set()
    status = _generate(repo, runner)
    assert len(runner.calls) - before == 4
    assert status["state"] == mmc.STATE_GENERATED
    assert status["pairs"]["sp500__T0"]["superseded"]


@patch("value_investor.research.agent._run_agent_prompt")
def test_initial_agent_passes_appendix_as_of_and_capture(mock_run: Any, tmp_path: Path) -> None:
    from value_investor.summary import CompanyReport

    mock_run.return_value = (
        "RESEARCH VERDICT\nVerdict: neutral\nRisk: low\nConfidence: 0.5\nRationale: ok",
        "a1",
    )
    report = CompanyReport.from_dict({"ticker": "ABC.L", "name": "ABC", "signal": "buy"})
    capture: dict[str, Any] = {}
    research_agent.run_initial_research_agent(
        report=report,
        sources_dir=tmp_path,
        api_key="k",
        model="grok-4.6",
        as_of_date="2026-11-10",
        prompt_appendix=mmc.COMPARISON_APPENDIX,
        capture=capture,
    )
    kwargs = mock_run.call_args.kwargs
    assert kwargs["prompt"].rstrip().endswith("(2 to 4 lines.)")
    assert kwargs["as_of_date"] == "2026-11-10"
    assert kwargs["capture"] is capture
    research_agent.run_initial_research_agent(report=report, sources_dir=tmp_path, api_key="k")
    plain = mock_run.call_args.kwargs
    assert "as_of_date" not in plain and "capture" not in plain
    assert "COMPARISON EVIDENCE" not in plain["prompt"]


def test_run_agent_prompt_fills_capture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class AgentCls:
        agent_id = "agent-1"

        def send(self, prompt: str) -> AgentCls:
            return self

        def wait(self) -> SimpleNamespace:
            return SimpleNamespace(id="run-1", result=" memo ")

        def close(self) -> None:
            return None

    monkeypatch.setattr(research_agent.Agent, "create", lambda _o: AgentCls())
    capture: dict[str, Any] = {}
    text, _ = research_agent._run_agent_prompt(
        prompt="p",
        api_key="k",
        model="grok-4.6",
        cwd=str(tmp_path),
        as_of_date="2026-11-10",
        capture=capture,
    )
    assert text == "memo" == capture["raw_text"]
    assert "Point-in-time rule" in capture["prompt"] and "2026-11-10" in capture["prompt"]
    assert capture["latency_seconds"] >= 0


def test_committed_manifest_matches_rule() -> None:
    manifest = json.loads(Path("docs/data/memo_model_comparison/manifest.json").read_text())
    assert manifest["decision_rule_version"] == "v2"
    assert manifest["amendment"]["owner_quote"] == "yes please"
    assert manifest["amendment"]["before_any_results"] is True
    assert manifest["judge"]["model"] == mmc.JUDGE_MODEL
    mmc.check_judge_model(manifest["judge"]["model"], manifest["models"])
    budget = manifest["budget"]
    assert budget["judge_estimated_total_usd"] == mmc.estimated_judge_usd(12) == 22.56
    assert budget["judge_estimated_total_usd"] <= budget["judge_cap_usd"]
    assert budget["comparison_estimated_total_usd"] <= budget["comparison_cap_usd"]


def test_committed_manifest_selection_unchanged() -> None:
    manifest = json.loads(Path("docs/data/memo_model_comparison/manifest.json").read_text())
    names = manifest["names"]
    assert len(names) == 12
    assert len({n["slug"] for n in names}) == 12
    assert manifest["models"] == {"incumbent": "composer-2.5", "challenger": "grok-4.6"}
    assert manifest["markets"][0] == "ftse350" and len(manifest["markets"]) == 4
    assert sum(1 for n in names if n["market"] == "ftse350") == mmc.FTSE_QUOTA
    assert sum(1 for n in names if n["bucket"] == "gate_flagged") == 4
    assert manifest["budget"]["estimated_total_usd"] <= manifest["budget"]["cap_usd"]
    assert manifest["influences_live"] is False


def test_workflow_and_email_exclusion() -> None:
    wf = Path(".github/workflows/memo-model-comparison.yml").read_text()
    assert "generate --apply --if-due" in wf and "decide --apply" in wf
    assert "judge --apply --if-due" in wf and "- judge" in wf
    assert "docs/data/memo_model_comparison/ratings.json" in wf
    assert "strategy_book_memo" not in wf
    email = Path(".github/workflows/email-report.yml").read_text()
    assert "docs/data/memo_model_comparison/" in email


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def test_commit_script_directory_exclude(tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    _git(tmp_path, "init", "--bare", "-b", "main", str(remote))
    _git(tmp_path, "clone", str(remote), str(work))
    for args in (("config", "user.email", "t@example.com"), ("config", "user.name", "t")):
        _git(work, *args)
    keep = work / "docs" / "data" / "latest.json"
    skip = work / "docs" / "data" / "memo_model_comparison" / "ratings.json"
    keep.parent.mkdir(parents=True)
    skip.parent.mkdir(parents=True)
    keep.write_text("{}\n")
    skip.write_text('{"owner": "fresh"}\n')
    _git(work, "add", ".")
    _git(work, "commit", "-m", "seed")
    _git(work, "push", "origin", "main")
    keep.write_text('{"n": 2}\n')
    skip.write_text('{"owner": "stale"}\n')
    script = Path("scripts/gha_commit_artifacts.sh").resolve()
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "GHA_COMMIT_OWNED": "docs/data",
        "GHA_COMMIT_EXCLUDE": "docs/data/memo_model_comparison/",
        "COMMIT_MESSAGE": "test",
        "GHA_COMMIT_SLEEP_BASE": "0",
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }
    result = subprocess.run(
        ["bash", str(script)], cwd=work, env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert "Excluding docs/data/memo_model_comparison/ratings.json" in result.stderr
    check = tmp_path / "check"
    _git(tmp_path, "clone", str(remote), str(check))
    assert json.loads((check / "docs/data/latest.json").read_text()) == {"n": 2}
    assert json.loads((check / "docs/data/memo_model_comparison/ratings.json").read_text()) == {
        "owner": "fresh"
    }


# --- rule v2: judge, calibration, decision ---------------------------------

GOOD_MARK = "12.3p per share"


def _shown(prompt: str, label: str) -> str:
    return prompt.split(f"=== MEMO {label} ===", 1)[1].split(f"=== END MEMO {label} ===", 1)[0]


class FakeJudge:
    """Prefers the memo whose quote is in the filing (``good``), or a fixed position."""

    def __init__(self, mode: str = "good", fail: bool = False) -> None:
        self.mode = mode
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kw: Any) -> str:
        self.calls.append(kw)
        kw["capture"].update(
            {"prompt": kw["prompt"], "latency_seconds": 3.0, "usage": {"charged_cents": 20.0}}
        )
        if self.fail:
            return "I cannot answer in JSON."
        good = {label: GOOD_MARK in _shown(kw["prompt"], label) for label in ("A", "B")}
        if self.mode == "position":
            pick = "A"
        elif self.mode == "bad":
            pick = "A" if not good["A"] else "B"
        else:
            pick = "A" if good["A"] else "B"
        other = "B" if pick == "A" else "A"

        def block(score: int) -> dict[str, Any]:
            row = {
                "score": score,
                "reason": "Quotes checked against the annual filing.",
                "quotes": [
                    {"source": "filings/bodies/annual.txt", "quote": "Net debt was £410m"},
                    {"source": "memo", "quote": "Filings support the buy case."},
                ],
            }
            return {key: dict(row) for key in mmc.RUBRIC}

        payload = {
            "scores": {pick: block(5), other: block(3)},
            "preferred": pick,
            "preference_reason": "Better grounded.",
            "claims_checked": [],
        }
        return "```json\n" + json.dumps(payload) + "\n```"


def _judge(
    root: Path,
    judge: FakeJudge,
    *,
    remaining: float = 100.0,
    spent: list[float] | None = None,
    models: list[str] | None = None,
    now: datetime = NOW,
) -> dict[str, Any]:
    ledger = spent if spent is not None else []
    return mmc.run_judge(
        root,
        now=now,
        api_key="k",
        runner=judge,
        list_models=lambda: models if models is not None else [mmc.JUDGE_MODEL, "grok-4.7"],
        budget_status=lambda: {"remaining_weekly_ops_usd": remaining},
        record_spend=ledger.append,
    )


def _owner(repo: Path, prefer: str | None, score: dict[str, int]) -> dict[str, Any]:
    """Fill ratings_template.json: ``prefer`` is a model id, or None for tie."""
    store = mmc.store_dir(repo)
    key = json.loads((store / "blind_key.json").read_text())
    ratings = json.loads((store / "ratings_template.json").read_text())
    for slug, row in ratings["names"].items():
        labels = key["names"][slug]
        row["preferred"] = (
            "tie" if prefer is None else next(lb for lb, m in labels.items() if m == prefer)
        )
        for label, model in labels.items():
            row[label] = {k: score[model] for k in mmc.RUBRIC}
    (store / "ratings.json").write_text(json.dumps(ratings), encoding="utf-8")
    return ratings


def _small_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mmc, "MIN_COMPLETE_PAIRS", 6)
    monkeypatch.setattr(mmc, "MIN_CHALLENGER_PREFERRED", 5)
    monkeypatch.setattr(mmc, "MAX_INCUMBENT_PREFERRED", 1)


def test_v1_manifest_refuses_generation_and_judge(repo: Path) -> None:
    store = mmc.store_dir(repo)
    (store / "manifest.json").write_text(json.dumps(_manifest(amend=False)), encoding="utf-8")
    runner = FakeRunner()
    status = _generate(repo, runner)
    assert runner.calls == []
    assert "generation refuses" in status["errors"][0]
    judge = FakeJudge()
    assert "judge refuses" in _judge(repo, judge)["errors"][0]
    assert judge.calls == []
    assert [f["title"] for f in mmc.findings(repo, NOW)] == [mmc.TITLE_FAILED]


def test_amend_refuses_once_generation_output_exists(repo: Path) -> None:
    store = mmc.store_dir(repo)
    base = _manifest(amend=False)
    _generate(repo, FakeRunner())
    with pytest.raises(ValueError, match="cannot amend"):
        mmc.amend_rule_v2(base, store=store)
    from value_investor.memo_model_comparison_cli import main

    assert main(["--repo-root", str(repo), "amend", "--apply"]) == 1


def test_judge_must_be_third_family_with_rate() -> None:
    models = {"incumbent": "composer-2.5", "challenger": "grok-4.6"}
    mmc.check_judge_model("gpt-5.6-luna", models, available=["gpt-5.6-luna"])
    mmc.check_judge_model("claude-haiku-4-5", models)
    assert mmc.model_family(mmc.JUDGE_MODEL) == "openai"
    for barred in ("composer-2", "default", "grok-4.7", "grok-4.5"):
        with pytest.raises(ValueError, match="family"):
            mmc.check_judge_model(barred, models)
    with pytest.raises(ValueError, match="no known model family"):
        mmc.check_judge_model("muse-spark-1.3", models)
    with pytest.raises(ValueError, match="no rate"):
        mmc.check_judge_model("claude-opus-5-5", models)
    with pytest.raises(ValueError, match="not available"):
        mmc.check_judge_model("gpt-5.6-luna", models, available=["grok-4.6"])
    # A judge sharing a family with either compared model is refused.
    with pytest.raises(ValueError, match="family"):
        mmc.check_judge_model("gpt-5.4-mini", {"incumbent": "gpt-5-mini", "challenger": "grok-4.6"})


def test_judge_unavailable_fails_closed(repo: Path) -> None:
    _generate(repo, FakeRunner())
    judge = FakeJudge()
    status = _judge(repo, judge, models=["composer-2.5", "grok-4.6"])
    assert judge.calls == []
    assert "judge model check failed" in status["errors"][0]
    assert [f["title"] for f in mmc.findings(repo, NOW)] == [mmc.TITLE_FAILED]


def test_judge_waits_for_generation(repo: Path) -> None:
    judge = FakeJudge()
    assert mmc.due_for_judge(repo) is False
    assert "generation not finished" in _judge(repo, judge)["errors"][0]
    assert judge.calls == []


def test_judge_runs_both_orders_blind_and_persists_evidence(repo: Path) -> None:
    _generate(repo, FakeRunner())
    judge = FakeJudge()
    spent: list[float] = []
    status = _judge(repo, judge, spent=spent)
    store = mmc.store_dir(repo)
    assert status["state"] == mmc.JUDGE_STATE_DONE
    assert len(judge.calls) == 4
    assert spent == [mmc.estimated_memo_usd(mmc.JUDGE_MODEL)] * 4
    assert status["spend"]["estimated_usd"] == pytest.approx(4 * 0.94)
    for call in judge.calls:
        prompt = call["prompt"]
        assert call["model"] == mmc.JUDGE_MODEL
        assert mmc.INCUMBENT_MODEL not in prompt and mmc.CHALLENGER_MODEL not in prompt
        assert "charged" not in prompt and "$" not in prompt
        assert call["cwd"].endswith("sources") is False
        assert str(Path(call["cwd"]) / "sources") in prompt
    # Each order shows the stored memos in swapped positions.
    t0 = [c["prompt"] for c in judge.calls if "(T0," in c["prompt"]]
    assert _shown(t0[0], "A") == _shown(t0[1], "B")
    record = json.loads((store / "judgements" / "sp500__T0" / "BA.json").read_text())
    assert record["ok"] is True and record["shown_as"] == {"A": "B", "B": "A"}
    assert record["raw_text"] and len(record["prompt_sha256"]) == 64
    for label in ("A", "B"):
        for key in mmc.RUBRIC:
            row = record["parsed"]["scores"][label][key]
            assert row["reason"] and row["quotes"]
    assert record["quote_check"]["found"] == record["quote_check"]["quotes"] == 12
    results = json.loads((store / "judge_results.json").read_text())
    key = json.loads((store / "blind_key.json").read_text())
    for pair in results["pairs"]:
        assert pair["order_consistent"] is True
        assert key["names"][pair["slug"]][pair["preferred"]] == mmc.CHALLENGER_MODEL
    assert mmc.due_for_judge(repo) is False
    _judge(repo, judge)
    assert len(judge.calls) == 4


def test_position_bias_counts_as_tie(repo: Path) -> None:
    _generate(repo, FakeRunner())
    _judge(repo, FakeJudge(mode="position"))
    results = json.loads((mmc.store_dir(repo) / "judge_results.json").read_text())
    assert [p["preferred"] for p in results["pairs"]] == ["tie", "tie"]
    assert all(not p["order_consistent"] for p in results["pairs"])
    assert all(p["picks_by_order"]["AB"] != p["picks_by_order"]["BA"] for p in results["pairs"])
    # Averaged over both orders each memo scores (5 + 3) / 2 per key.
    assert results["pairs"][0]["scores"]["A"]["total"] == 12.0


def test_model_names_redacted_from_memo_text() -> None:
    text, hits = mmc.redact_model_names("As Grok-4.6 I think; Composer agrees; GPT too.")
    assert hits == 3 and "rok" not in text and "omposer" not in text


def test_invalid_judge_output_retries_once_then_exhausts(repo: Path) -> None:
    _generate(repo, FakeRunner())
    judge = FakeJudge(fail=True)
    first = _judge(repo, judge)
    assert first["state"] == mmc.JUDGE_STATE_INCOMPLETE
    assert any("invalid judge output" in e for e in first["errors"])
    record = json.loads((mmc.store_dir(repo) / "judgements" / "sp500__T0" / "AB.json").read_text())
    assert record["ok"] is False and record["raw_text"] == "I cannot answer in JSON."
    _judge(repo, judge)
    calls = len(judge.calls)
    assert calls == 8
    _judge(repo, judge)
    assert len(judge.calls) == calls
    assert not (mmc.store_dir(repo) / "review.md").exists()


def test_parse_judge_output_schema() -> None:
    payload, problems = mmc.parse_judge_output('{"preferred": "C", "scores": {}}')
    assert payload is not None and "preferred must be A, B or tie" in problems
    assert any("A.evidence.quotes" in p for p in problems)
    assert mmc.parse_judge_output("nothing")[1] == ["no JSON object"]


def test_judge_budget_guards(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _generate(repo, FakeRunner())
    judge = FakeJudge()
    status = _judge(repo, judge, remaining=mmc.STRATEGY_BOOK_RESERVE_USD + 0.5)
    assert judge.calls == []
    assert status["budget_stop"]["kind"] == "weekly_headroom"
    assert mmc.due_for_judge(repo) is True
    monkeypatch.setattr(mmc, "JUDGE_BUDGET_CAP_USD", 1.0)
    status = _judge(repo, judge)
    assert len(judge.calls) == 1
    assert status["budget_stop"]["kind"] == "cap"
    assert mmc.due_for_judge(repo) is False


def test_judge_refuses_changed_sources(repo: Path, tmp_path: Path) -> None:
    _generate(repo, FakeRunner())
    (tmp_path / "src_sources" / "filings" / "bodies" / "late.txt").write_text("x", encoding="utf-8")
    shutil.rmtree(mmc.work_dir(repo))
    judge = FakeJudge()
    status = _judge(repo, judge)
    assert judge.calls == []
    assert any("sources changed since generation" in e for e in status["errors"])


def test_calibration_sample_selection_rule() -> None:
    def memo(flags: int, rate: float, effect: str = "allows") -> dict[str, Any]:
        return {
            "checks": {"hallucination_flag_total": flags, "quote_resolution_rate": rate},
            "book_effect": effect,
        }

    pairs = [{"slug": f"s{i}", "preferred": pref} for i, pref in enumerate("AABtBtA")]
    for pair in pairs:
        pair["preferred"] = "tie" if pair["preferred"] == "t" else pair["preferred"]
    memos = {
        "s0": {"A": memo(0, 1.0), "B": memo(2, 1.0)},  # judge A, mechanical A: agree
        "s1": {"A": memo(3, 1.0), "B": memo(1, 1.0)},  # judge A, mechanical B: disagree
        "s2": {"A": memo(0, 0.5), "B": memo(0, 0.9)},  # judge B, mechanical B (rate tiebreak)
        "s3": {"A": memo(0, 1.0), "B": memo(0, 1.0, "blocks")},  # book-effect disagreement
        "s4": {"A": memo(0, 0.9), "B": memo(0, 0.5)},  # judge B, mechanical A: disagree
        "s5": {"A": memo(1, 1.0), "B": memo(0, 1.0)},  # judge tie: never a mechanical disagreement
        "s6": {"A": memo(0, 1.0), "B": memo(0, 1.0)},  # judge A, mechanical tie
    }
    sample = mmc.select_calibration("cid", pairs, memos)
    reasons = {row["slug"]: row["reasons"] for row in sample}
    assert reasons["s1"] == ["judge_vs_mechanical"]
    assert reasons["s3"] == ["book_effect_disagreement"]
    assert reasons["s4"] == ["judge_vs_mechanical"]
    assert len(sample) == mmc.CALIBRATION_MIN_SAMPLE
    topped = [slug for slug, why in reasons.items() if why == ["top_up"]]
    assert len(topped) == 1 and topped[0] in {"s0", "s2", "s6"}  # non-tie judge pick first
    expected = min(("s0", "s2", "s6"), key=lambda s: mmc._topup_rank("cid", s))
    assert topped == [expected]
    assert [row["slug"] for row in sample] == sorted(reasons, key=lambda s: int(s[1:]))
    assert mmc.select_calibration("cid", pairs, memos) == sample
    assert [mmc.calibration_need(n) for n in (4, 5, 6, 8, 12)] == [3, 4, 5, 6, 9]


def test_calibration_takes_every_book_effect_disagreement(repo6: Path) -> None:
    _generate(repo6, FakeRunner(verdicts={mmc.CHALLENGER_MODEL: "pass"}))
    _judge(repo6, FakeJudge())
    store = mmc.store_dir(repo6)
    cal = json.loads((store / "calibration.json").read_text())
    assert len(cal["sample"]) == 6
    assert all("book_effect_disagreement" in row["reasons"] for row in cal["sample"])
    review = (store / "review.md").read_text()
    assert review.count("### Memo A") == 6
    for word in (mmc.JUDGE_MODEL, mmc.INCUMBENT_MODEL, mmc.CHALLENGER_MODEL, "judge_vs", "top_up"):
        assert word not in review


def test_review_covers_only_the_sample(repo6: Path) -> None:
    _generate(repo6, FakeRunner())
    _judge(repo6, FakeJudge())
    store = mmc.store_dir(repo6)
    cal = json.loads((store / "calibration.json").read_text())
    assert [row["reasons"] for row in cal["sample"]] == [["top_up"]] * 4
    template = json.loads((store / "ratings_template.json").read_text())
    assert sorted(template["names"]) == sorted(row["slug"] for row in cal["sample"])
    assert (store / "review.md").read_text().count("### Memo B") == 4
    assert cal["need_agree"] == 3


def test_decision_v2_trusted_judge_switches(repo6: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _small_rule(monkeypatch)
    _generate(repo6, FakeRunner())
    _judge(repo6, FakeJudge())
    _owner(repo6, mmc.CHALLENGER_MODEL, {mmc.CHALLENGER_MODEL: 5, mmc.INCUMBENT_MODEL: 3})
    verdict = mmc.decide_from_store(mmc.store_dir(repo6))
    assert verdict["judge_trusted"] is True and verdict["governing"] == "judge"
    assert verdict["outcome"] == "switch", verdict["checks"]
    assert verdict["checks"]["judge_prefers_challenger"]["value"]["challenger"] == 6
    assert verdict["checks"]["judge_rubric_gain"]["value"] == 6.0
    assert verdict["calibration"] == {**verdict["calibration"], "sample": 4, "agree": 4, "need": 3}
    assert verdict["influences_live"] is False


def test_decision_v2_failed_calibration_owner_decides(
    repo6: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _small_rule(monkeypatch)
    _generate(repo6, FakeRunner())
    _judge(repo6, FakeJudge())
    _owner(repo6, mmc.INCUMBENT_MODEL, {mmc.CHALLENGER_MODEL: 3, mmc.INCUMBENT_MODEL: 4})
    verdict = mmc.decide_from_store(mmc.store_dir(repo6))
    assert verdict["judge_trusted"] is False and verdict["governing"] == "owner_sample"
    assert verdict["outcome"] == "keep"
    assert verdict["checks"]["judge_calibration"]["ok"] is False


def test_decision_v2_untrusted_judge_overwhelming_owner_switches(
    repo6: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _small_rule(monkeypatch)
    _generate(repo6, FakeRunner())
    _judge(repo6, FakeJudge(mode="position"))
    _owner(repo6, mmc.CHALLENGER_MODEL, {mmc.CHALLENGER_MODEL: 5, mmc.INCUMBENT_MODEL: 3})
    verdict = mmc.decide_from_store(mmc.store_dir(repo6))
    assert verdict["judge_trusted"] is False
    assert verdict["owner_sample"]["overwhelming_challenger"] is True
    assert verdict["outcome"] == "switch"
    # Owner ties on the sample: not overwhelming, and fewer than 10 pairs is never keep.
    _owner(repo6, None, {mmc.CHALLENGER_MODEL: 4, mmc.INCUMBENT_MODEL: 4})
    verdict = mmc.decide_from_store(mmc.store_dir(repo6))
    assert verdict["owner_sample"]["overwhelming_challenger"] is False
    assert verdict["outcome"] in {"keep", "inconclusive_keep"}


def test_decision_v2_owner_governs_book_effect_disagreements(
    repo6: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _small_rule(monkeypatch)
    _generate(repo6, FakeRunner(verdicts={mmc.CHALLENGER_MODEL: "pass"}))
    _judge(repo6, FakeJudge())
    _owner(repo6, mmc.INCUMBENT_MODEL, {mmc.CHALLENGER_MODEL: 3, mmc.INCUMBENT_MODEL: 4})
    verdict = mmc.decide_from_store(mmc.store_dir(repo6))
    assert len(verdict["calibration"]["owner_governed_book_effect"]) == 6
    assert verdict["checks"]["judge_prefers_challenger"]["value"]["incumbent"] == 6
    assert verdict["checks"]["book_effect_disagreements"]["ok"] is False
    assert verdict["outcome"] == "keep" and verdict["judge_trusted"] is False


def test_decision_v2_needs_ten_pairs_by_default(repo6: Path) -> None:
    _generate(repo6, FakeRunner())
    _judge(repo6, FakeJudge())
    _owner(repo6, mmc.CHALLENGER_MODEL, {mmc.CHALLENGER_MODEL: 5, mmc.INCUMBENT_MODEL: 3})
    verdict = mmc.decide_from_store(mmc.store_dir(repo6))
    assert verdict["checks"]["complete_pairs"]["ok"] is False
    assert verdict["outcome"] == "inconclusive_keep"


def test_findings_lifecycle(repo: Path) -> None:
    assert [f["title"] for f in mmc.findings(repo, NOW)] == [mmc.TITLE_AWAITING]
    _generate(repo, FakeRunner())
    assert [f["title"] for f in mmc.findings(repo, NOW)] == [mmc.TITLE_AWAITING_JUDGE]
    _judge(repo, FakeJudge())
    ready = mmc.findings(repo, NOW)
    assert [f["title"] for f in ready] == [mmc.TITLE_READY]
    assert "0/2 calibration names rated" in ready[0]["summary"]
    stale = mmc.findings(repo, NOW + timedelta(days=mmc.REVIEW_STALE_DAYS + 1))
    assert stale[0]["title"] == mmc.TITLE_STALE and stale[0]["severity"] == "warn"
    _owner(repo, mmc.CHALLENGER_MODEL, {mmc.CHALLENGER_MODEL: 5, mmc.INCUMBENT_MODEL: 3})
    decided = mmc.findings(repo, NOW)
    assert decided[0]["title"] == mmc.TITLE_DECIDED
    assert "judge_trusted false" in decided[0]["summary"]  # sample of 2 is below the minimum
    assert all(f["auto_fixable"] is False for f in decided + ready + stale)


def test_ops_monitor_check_wraps_findings(repo: Path) -> None:
    rows = check_memo_model_comparison(repo_root=repo, now=NOW)
    assert [r.title for r in rows] == [mmc.TITLE_AWAITING]
    assert rows[0].auto_fixable is False and rows[0].category == "research"
    missing = check_memo_model_comparison(repo_root=repo / "nowhere", now=NOW)
    assert missing[0].title == mmc.TITLE_FAILED


def test_cli_judge_and_decide(repo: Path) -> None:
    from value_investor.memo_model_comparison_cli import main

    assert main(["--repo-root", str(repo), "judge", "--if-due"]) == 0
    _generate(repo, FakeRunner())
    _judge(repo, FakeJudge())
    assert main(["--repo-root", str(repo), "judge", "--apply", "--if-due"]) == 0
    assert main(["--repo-root", str(repo), "decide"]) == 1
    _owner(repo, mmc.CHALLENGER_MODEL, {mmc.CHALLENGER_MODEL: 5, mmc.INCUMBENT_MODEL: 3})
    assert main(["--repo-root", str(repo), "decide", "--apply"]) == 0
    decision = json.loads((mmc.store_dir(repo) / "decision.json").read_text())
    assert decision["decision_rule_version"] == "v2" and "judge_trusted" in decision
    assert main(["--repo-root", str(repo), "select", "--apply"]) == 1  # manifest is frozen
