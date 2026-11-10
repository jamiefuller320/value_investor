"""Memo model comparison: selection, frozen inputs, scoring, blind review, decision, ops."""

from __future__ import annotations

import json
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


def _manifest(names: int = 2) -> dict[str, Any]:
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
    return {
        "schema_version": 1,
        "comparison_id": "test-comparison",
        "names": entries,
        "models": {"incumbent": mmc.INCUMBENT_MODEL, "challenger": mmc.CHALLENGER_MODEL},
        "budget": {"estimated_total_usd": 2.88, "cap_usd": mmc.BUDGET_CAP_USD},
    }


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


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "repo"
    store = mmc.store_dir(root)
    store.mkdir(parents=True)
    (store / "manifest.json").write_text(json.dumps(_manifest()), encoding="utf-8")
    sources = _sources(tmp_path)
    monkeypatch.setattr(mmc, "_sources_for", lambda entry, _root: sources)
    monkeypatch.setattr(
        mmc, "_report_for", lambda entry, _root: SimpleNamespace(ticker=entry["ticker"])
    )
    return root


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
    assert status["state"] == mmc.STATE_READY
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
    review = (store / "review.md").read_text()
    memo_a = (store / "memos" / "sp500__T0" / "A.json").read_text()
    for text in (review, memo_a):
        assert mmc.INCUMBENT_MODEL not in text and mmc.CHALLENGER_MODEL not in text
        assert "charged" not in text and "latency" not in text
    assert "### Memo A" in review and "### Memo B" in review
    results = json.loads((store / "results.json").read_text())
    assert results["verdict_agreement"] == {"agree": 0, "of": 2, "share": 0.0}
    assert results["book_effect_agreement"]["agree"] == 0
    assert results["by_model"][mmc.CHALLENGER_MODEL]["blocks"] == 2
    assert results["by_model"][mmc.CHALLENGER_MODEL]["charged_usd_per_memo"] == 0.5
    assert (store / "ratings_template.json").is_file()
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
    assert status["state"] == mmc.STATE_READY
    assert status["pairs"]["sp500__T0"]["superseded"]


def _ratings(repo: Path, prefer: str, score: dict[str, int]) -> dict[str, Any]:
    store = mmc.store_dir(repo)
    key = json.loads((store / "blind_key.json").read_text())
    ratings = json.loads((store / "ratings_template.json").read_text())
    for slug, row in ratings["names"].items():
        labels = key["names"][slug]
        pick = next(label for label, model in labels.items() if model == prefer)
        row["preferred"] = pick
        for label, model in labels.items():
            row[label] = {k: score[model] for k in mmc.RUBRIC}
    (store / "ratings.json").write_text(json.dumps(ratings), encoding="utf-8")
    return ratings


def test_decision_rule_switch_and_keep(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _generate(repo, FakeRunner())
    store = mmc.store_dir(repo)
    manifest = json.loads((store / "manifest.json").read_text())
    results = json.loads((store / "results.json").read_text())
    key = json.loads((store / "blind_key.json").read_text())
    monkeypatch.setattr(mmc, "MIN_COMPLETE_PAIRS", 2)
    monkeypatch.setattr(mmc, "MIN_CHALLENGER_PREFERRED", 2)
    win = _ratings(repo, mmc.CHALLENGER_MODEL, {mmc.CHALLENGER_MODEL: 5, mmc.INCUMBENT_MODEL: 3})
    verdict = mmc.decide(manifest, results, win, key)
    assert verdict["outcome"] == "switch", verdict["checks"]
    assert verdict["checks"]["weekly_cost_fits"]["value"]["weekly_high_usd"] == 17.5
    lose = _ratings(repo, mmc.INCUMBENT_MODEL, {mmc.CHALLENGER_MODEL: 3, mmc.INCUMBENT_MODEL: 4})
    assert mmc.decide(manifest, results, lose, key)["outcome"] == "keep"
    assert verdict["influences_live"] is False


def test_findings_lifecycle(repo: Path) -> None:
    assert [f["title"] for f in mmc.findings(repo, NOW)] == [mmc.TITLE_AWAITING]
    _generate(repo, FakeRunner())
    ready = mmc.findings(repo, NOW)
    assert [f["title"] for f in ready] == [mmc.TITLE_READY]
    assert "0/2 names rated" in ready[0]["summary"]
    stale = mmc.findings(repo, NOW + timedelta(days=mmc.REVIEW_STALE_DAYS + 1))
    assert stale[0]["title"] == mmc.TITLE_STALE and stale[0]["severity"] == "warn"
    _ratings(repo, mmc.CHALLENGER_MODEL, {mmc.CHALLENGER_MODEL: 5, mmc.INCUMBENT_MODEL: 3})
    decided = mmc.findings(repo, NOW)
    assert decided[0]["title"] == mmc.TITLE_DECIDED
    assert all(f["auto_fixable"] is False for f in decided + ready + stale)


def test_ops_monitor_check_wraps_findings(repo: Path) -> None:
    rows = check_memo_model_comparison(repo_root=repo, now=NOW)
    assert [r.title for r in rows] == [mmc.TITLE_AWAITING]
    assert rows[0].auto_fixable is False and rows[0].category == "research"
    missing = check_memo_model_comparison(repo_root=repo / "nowhere", now=NOW)
    assert missing[0].title == mmc.TITLE_FAILED


def test_cli_decide_refuses_incomplete_ratings(repo: Path) -> None:
    from value_investor.memo_model_comparison_cli import main

    _generate(repo, FakeRunner())
    assert main(["--repo-root", str(repo), "decide"]) == 1
    _ratings(repo, mmc.CHALLENGER_MODEL, {mmc.CHALLENGER_MODEL: 5, mmc.INCUMBENT_MODEL: 3})
    assert main(["--repo-root", str(repo), "decide", "--apply"]) == 0
    assert (mmc.store_dir(repo) / "decision.json").is_file()
    assert main(["--repo-root", str(repo), "select", "--apply"]) == 1  # manifest is frozen


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
