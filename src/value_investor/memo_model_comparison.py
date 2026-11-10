"""Side-by-side memo model comparison (owner, 2026-11-10). Observe-only.

Incumbent ``composer-2.5`` against the strongest Grok configured in
``agent_model_policy`` on a fixed set of names. Both memos for a name read one
frozen copy of that name's research sources, the same production prompt (plus
one comparison appendix asking for checkable evidence), and the same as-of
date. Everything is written under ``docs/data/memo_model_comparison/``. Nothing
here writes the research store, the memo log, the strategy book or any
decision path, and the strategy-book memo job is not imported for its runner.

Runbook and the pre-declared decision rule: docs/ops/memo-model-comparison.md.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from statistics import mean, median
from typing import Any

from value_investor.agent_model_policy import (
    MODEL_API_RATES,
    SPEND_POOL_WEEKLY_OPS,
    record_estimated_spend,
    weekly_ops_budget_status,
)
from value_investor.storage import read_json, write_json

SCHEMA_VERSION = 1
RULE_VERSION = "v1"
COMPARISON_ID = "memo-model-comparison-2026-11"

STORE_REL = Path("docs/data/memo_model_comparison")
WORK_REL = Path("output/memo_model_comparison")

INCUMBENT_MODEL = "composer-2.5"
# Registration section 11 estimate for one strategy-book memo on the incumbent.
INCUMBENT_MEMO_USD = 0.40

FTSE_QUOTA = 4
LIBRARY_QUOTAS = (3, 3, 2)
CONTRAST_PER_MARKET = 1
MAX_ATTEMPTS = 2
REVIEW_STALE_DAYS = 14
# Comparison budget line: 12 names x (0.40 + 1.04) = 17.28 estimated, capped here.
BUDGET_CAP_USD = 22.0
# Left in weekly_ops for the strategy-book memo job: its weekly high estimate
# (35 memos at $0.40) plus the shared minimum headroom.
STRATEGY_BOOK_RESERVE_USD = 14.0 + 8.0

TITLE_AWAITING = "Memo model comparison awaiting generation"
TITLE_READY = "Memo model comparison ready for owner review"
TITLE_STALE = "Memo model comparison owner review stale"
TITLE_DECIDED = "Memo model comparison decided"
TITLE_FAILED = "Memo model comparison failed"

STATE_SELECTED = "selected"
STATE_INCOMPLETE = "incomplete"
STATE_READY = "ready_for_review"

RUBRIC = {
    "evidence": "Evidence grounding: claims are tied to the filings and nothing looks invented.",
    "thesis_break": "Thesis breaks: it says concretely what would make this a do-not-own name.",
    "verdict_justified": "Verdict justified: verdict and confidence match the evidence shown.",
}

COMPARISON_APPENDIX = """COMPARISON EVIDENCE (required for this run, after RESEARCH VERDICT)
Write these three sections exactly, with paths relative to the sources folder above:

EVIDENCE
- [filings/bodies/<file>] "<verbatim quote from that file, at most 200 characters>" — <what it supports>
(3 to 8 lines. Quote the file exactly; do not paraphrase inside the quotes.)

NUMBERS
- <metric> | <value as written in the file> | <period> | [<path>]
(Up to 6 figures you relied on, each copied from the cited file.)

THESIS BREAKS
- <a concrete fact that, if it appeared, would make this name a pass>
(2 to 4 lines.)"""

_APPENDIX_HEADINGS = {
    "EVIDENCE": "evidence",
    "NUMBERS": "numbers",
    "THESIS BREAKS": "thesis_breaks",
}
_STOP_HEADINGS = {"RESEARCH VERDICT", "COMPARISON EVIDENCE"}
_EVIDENCE_RE = re.compile(
    r"^\s*[-*]\s*\[(?P<path>[^\]]+)\]\s*[\"“](?P<quote>.+?)[\"”]\s*(?:[—–-]+\s*(?P<claim>.*))?$"
)
_NUMBER_RE = re.compile(
    r"^\s*[-*]\s*(?P<metric>[^|]+)\|\s*(?P<value>[^|]+)\|\s*(?P<period>[^|]*)\|\s*\[(?P<path>[^\]]+)\]"
)
_NUMBER_TOKEN_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
_YEAR_RE = re.compile(r"\b(20\d{2})\b")


def store_dir(repo_root: Path) -> Path:
    return Path(repo_root) / STORE_REL


def work_dir(repo_root: Path) -> Path:
    return Path(repo_root) / WORK_REL


def _grok_version(model_id: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", model_id))


def strongest_configured_grok(rates: dict[str, Any] | None = None) -> str:
    """Highest-version ``grok-*`` id with a rate in ``agent_model_policy``."""
    ids = [
        mid for mid in (rates if rates is not None else MODEL_API_RATES) if mid.startswith("grok-")
    ]
    if not ids:
        raise ValueError("no grok model configured in MODEL_API_RATES")
    return max(ids, key=_grok_version)


CHALLENGER_MODEL = strongest_configured_grok()


def estimated_memo_usd(model_id: str) -> float:
    from value_investor.research.model_ab import estimate_model_memo_usd

    return estimate_model_memo_usd(model_id, baseline_usd=INCUMBENT_MEMO_USD)


def estimated_total_usd(names: int, models: tuple[str, str]) -> float:
    return round(names * sum(estimated_memo_usd(model) for model in models), 2)


def _slug(market: str, ticker: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", f"{market}__{ticker}")


# --- selection -------------------------------------------------------------


@dataclass
class Candidate:
    market: str
    ticker: str
    name: str
    signal: str
    session: str
    decline: str
    sector: str
    price_entry: bool
    alternative_entry: bool
    rsi: float
    filings_with_body: int
    adjusted_signal: str | None
    screen_verdict: str | None

    @property
    def flagged(self) -> bool:
        return self.decline != "clear" or self.sector != "sound"

    @property
    def adverse(self) -> bool:
        """A scored adverse verdict, as opposed to ``insufficient_data`` or a missing store."""
        return self.decline == "declining" or self.sector == "headwind"

    def entry_rank(self) -> tuple[int, int, float, str]:
        return (
            0 if self.price_entry else 1,
            0 if self.alternative_entry else 1,
            self.rsi,
            self.ticker,
        )

    def contrast_rank(self) -> tuple[int, int, int, float, str]:
        return (0 if self.adverse else 1, *self.entry_rank())

    def to_dict(self, bucket: str) -> dict[str, Any]:
        return {
            "slug": _slug(self.market, self.ticker),
            "market": self.market,
            "ticker": self.ticker,
            "name": self.name,
            "bucket": bucket,
            "signal": self.signal,
            "session": self.session,
            "decline_verdict": self.decline,
            "sector_verdict": self.sector,
            "price_entry": self.price_entry,
            "alternative_entry": self.alternative_entry,
            "rsi_14": round(self.rsi, 2),
            "filings_with_body": self.filings_with_body,
            "adjusted_signal": self.adjusted_signal,
            "screen_research_verdict": self.screen_verdict,
        }


def _market_session(paths: Any, market: str, before: date) -> date | None:
    """Newest chart bar strictly before ``before`` across the market's buy tier."""
    from value_investor.paper_fund import BUY_SIGNALS
    from value_investor.price_charts import chart_filename
    from value_investor.strategy_book_signals import (
        history_dir_for,
        load_chart_closes,
        newest_screen_run,
        screen_rows,
    )

    _path, payload, _day = newest_screen_run(history_dir_for(paths, market), before)
    latest: date | None = None
    for ticker, row in screen_rows(payload).items():
        if str(row.get("signal") or "").strip() not in BUY_SIGNALS:
            continue
        _days, _closes, all_days = load_chart_closes(
            paths.charts / chart_filename(ticker), date(9999, 12, 31)
        )
        for day in all_days:
            if day < before and (latest is None or day > latest):
                latest = day
    return latest


def market_candidates(
    paths: Any, market: str, before: date
) -> tuple[list[Candidate], dict[str, Any]]:
    from value_investor.buy_tier_flip_lag import _index_meta
    from value_investor.gate_store_history import GateHistory
    from value_investor.library_dedupe import research_home_market
    from value_investor.sector_headwind_gate import FTSE_MARKET
    from value_investor.strategy_book_signals import evaluate_market, research_root_for

    session = _market_session(paths, market, before)
    stats: dict[str, Any] = {"session": session.isoformat() if session else None}
    if session is None:
        stats.update({"buy_tier": 0, "candidates": 0})
        return [], stats
    decline, sector = GateHistory.load(paths.decline, paths.sector).in_force(session)
    evaluated = evaluate_market(
        market,
        session,
        paths=paths,
        decline_payload=decline,
        sector_payload=sector,
        load_stores=False,
    )
    root = research_root_for(paths, market)
    out: list[Candidate] = []
    skipped = {"other_home_market": 0, "no_key_bodies": 0, "no_rsi": 0}
    for row in evaluated.names:
        if market != FTSE_MARKET and research_home_market(paths.library, row.ticker) != market:
            skipped["other_home_market"] += 1
            continue
        meta = _index_meta(row.ticker, research_root=root)
        if not meta.get("key_bodies"):
            skipped["no_key_bodies"] += 1
            continue
        rsi = (row.checks["rsi_below_35"].detail or {}).get("rsi_14")
        if rsi is None:
            skipped["no_rsi"] += 1
            continue
        screen = row.screen_row
        out.append(
            Candidate(
                market=market,
                ticker=row.ticker,
                name=str(screen.get("name") or row.ticker),
                signal=str(screen.get("signal") or ""),
                session=session.isoformat(),
                decline=row.checks["part2_decline"].reason,
                sector=row.checks["part3_sector"].reason,
                price_entry=row.price_entry,
                alternative_entry=row.checks["alternative_entry"].passed,
                rsi=float(rsi),
                filings_with_body=int(meta.get("filings_with_body") or 0),
                adjusted_signal=_clean(screen.get("adjusted_signal")),
                screen_verdict=_clean(screen.get("research_verdict")),
            )
        )
    stats.update({"buy_tier": evaluated.buy_tier, "candidates": len(out), "skipped": skipped})
    return out, stats


def _clean(value: Any) -> str | None:
    text = str(value or "").strip()
    return None if text.lower() in {"", "none", "nan", "null"} else text


def pick_market(candidates: list[Candidate], quota: int) -> list[tuple[Candidate, str]]:
    """One gate-flagged contrast name, the rest nearest the entry rule."""
    flagged = sorted((c for c in candidates if c.flagged), key=Candidate.contrast_rank)
    clean = sorted((c for c in candidates if not c.flagged), key=Candidate.entry_rank)
    contrast = flagged[: min(CONTRAST_PER_MARKET, quota)]
    entry = clean[: quota - len(contrast)]
    spare = quota - len(contrast) - len(entry)
    contrast += flagged[len(contrast) : len(contrast) + spare]
    return [(c, "near_entry") for c in entry] + [(c, "gate_flagged") for c in contrast]


SELECTION_RULE = (
    "Rule v1. Markets: FTSE 350 plus the three graduated library markets with the most "
    "candidates (ties by market id). Session: each market's newest chart bar before the "
    "selection date; gate verdicts in force on that session. Candidate: a buy-tier row "
    "(buy or strong_buy) on that session's screen, research home in that market (library "
    "names deduplicated by research_home_market), key filing bodies in the filings index "
    "on disk at selection time, and a 14-day RSI on the session. Quotas: FTSE 4, library "
    "3, 3 and 2. In each market one contrast slot goes to a gate-flagged candidate "
    "(operating decline not clear or sector not sound), preferring a scored declining or "
    "headwind verdict over insufficient_data; the other slots go to unflagged "
    "candidates nearest the entry rule: primary entry first, then the alternative entry, "
    "then lowest RSI, then ticker. Short buckets fill from the other bucket."
)


def select_names(repo_root: Path, *, before: date, now: datetime | None = None) -> dict[str, Any]:
    from value_investor.sector_headwind_gate import FTSE_MARKET
    from value_investor.strategy_book_signals import repo_paths, universe_markets

    paths = repo_paths(Path(repo_root))
    markets = universe_markets(paths.market_status)
    pools: dict[str, list[Candidate]] = {}
    stats: dict[str, Any] = {}
    for market in markets:
        pools[market], stats[market] = market_candidates(paths, market, before)
    library = sorted(
        (m for m in markets if m != FTSE_MARKET and pools[m]),
        key=lambda m: (-len(pools[m]), m),
    )[: len(LIBRARY_QUOTAS)]
    chosen: list[dict[str, Any]] = []
    for market, quota in [(FTSE_MARKET, FTSE_QUOTA), *zip(library, LIBRARY_QUOTAS, strict=False)]:
        for cand, bucket in pick_market(pools.get(market, []), quota):
            chosen.append(cand.to_dict(bucket))
    moment = now or datetime.now(UTC)
    models = (INCUMBENT_MODEL, CHALLENGER_MODEL)
    return {
        "schema_version": SCHEMA_VERSION,
        "comparison_id": COMPARISON_ID,
        "generated_at": moment.isoformat(),
        "selected_before": before.isoformat(),
        "rule_version": RULE_VERSION,
        "selection_rule": SELECTION_RULE,
        "markets": [FTSE_MARKET, *library],
        "market_pools": stats,
        "names": chosen,
        "models": {"incumbent": INCUMBENT_MODEL, "challenger": CHALLENGER_MODEL},
        "budget": {
            "cap_usd": BUDGET_CAP_USD,
            "estimated_usd_per_memo": {model: estimated_memo_usd(model) for model in models},
            "estimated_total_usd": estimated_total_usd(len(chosen), models),
            "pool": SPEND_POOL_WEEKLY_OPS,
            "strategy_book_reserve_usd": STRATEGY_BOOK_RESERVE_USD,
        },
        "observe_only": True,
        "influences_live": False,
    }


# --- inputs ----------------------------------------------------------------


def snapshot_sources(source: Path, dest: Path) -> dict[str, Any]:
    """Copy one sources folder; return a digest over relative paths and bytes."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, dest)
    else:
        dest.mkdir(parents=True)
    digest = hashlib.sha256()
    files = 0
    bodies = 0
    for path in sorted(p for p in dest.rglob("*") if p.is_file()):
        rel = path.relative_to(dest).as_posix()
        digest.update(rel.encode("utf-8") + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
        files += 1
        if rel.startswith("filings/bodies/"):
            bodies += 1
    return {"sha256": digest.hexdigest(), "files": files, "filing_bodies": bodies}


def blind_labels(comparison_id: str, slug: str) -> dict[str, str]:
    """Deterministic, per-name coin flip for which model is memo A."""
    flip = int(hashlib.sha256(f"{comparison_id}|{slug}".encode()).hexdigest(), 16) % 2
    first, second = (
        (INCUMBENT_MODEL, CHALLENGER_MODEL) if flip == 0 else (CHALLENGER_MODEL, INCUMBENT_MODEL)
    )
    return {"A": first, "B": second}


# --- scoring ---------------------------------------------------------------


def _normalise(text: str) -> str:
    table = str.maketrans({"“": '"', "”": '"', "’": "'", "‘": "'", "–": "-", "—": "-"})
    return " ".join(text.translate(table).lower().split())


def _digits(text: str) -> str:
    return re.sub(r"(?<=\d),(?=\d)", "", text)


def parse_appendix(raw: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {key: [] for key in _APPENDIX_HEADINGS.values()}
    current: str | None = None
    for line in raw.splitlines():
        heading = line.strip().lstrip("#").strip().strip("*").strip().rstrip(":").upper()
        if heading in _APPENDIX_HEADINGS:
            current = _APPENDIX_HEADINGS[heading]
            continue
        if heading in _STOP_HEADINGS or heading.startswith("COMPARISON EVIDENCE"):
            current = None
            continue
        if current and line.strip().startswith(("-", "*")):
            sections[current].append(line.strip())
    return sections


def _resolve(sources_dir: Path, cited: str) -> Path | None:
    text = cited.strip().strip("`").strip()
    root = sources_dir.resolve()
    if Path(text).is_absolute() and Path(text).resolve().is_relative_to(root):
        text = Path(text).resolve().relative_to(root).as_posix()
    elif "/sources/" in text:
        text = text.rsplit("/sources/", 1)[1]
    text = text.removeprefix("./")
    candidate = (root / text).resolve()
    if root not in candidate.parents or not candidate.is_file():
        return None
    return candidate


def _file_text(path: Path, cache: dict[Path, str]) -> str:
    if path not in cache:
        cache[path] = path.read_text(encoding="utf-8", errors="replace")
    return cache[path]


def score_memo(raw: str, *, sources_dir: Path, as_of: date) -> dict[str, Any]:
    """Automated checks on one memo against its own frozen sources."""
    sections = parse_appendix(raw)
    cache: dict[Path, str] = {}
    evidence: list[dict[str, Any]] = []
    for line in sections["evidence"]:
        match = _EVIDENCE_RE.match(line)
        if not match:
            evidence.append(
                {"line": line, "parsed": False, "resolves": False, "quote_found": False}
            )
            continue
        path = _resolve(sources_dir, match.group("path"))
        found = bool(
            path is not None
            and _normalise(match.group("quote")) in _normalise(_file_text(path, cache))
        )
        evidence.append(
            {
                "path": match.group("path").strip(),
                "parsed": True,
                "resolves": path is not None,
                "filing_body": bool(path is not None and "filings/bodies/" in path.as_posix()),
                "quote_found": found,
            }
        )
    numbers: list[dict[str, Any]] = []
    for line in sections["numbers"]:
        match = _NUMBER_RE.match(line)
        token = _NUMBER_TOKEN_RE.search(match.group("value")) if match else None
        if not match or token is None:
            numbers.append({"line": line, "checkable": False, "found": False})
            continue
        path = _resolve(sources_dir, match.group("path"))
        value = _digits(token.group(0)).lstrip("-")
        found = False
        if path is not None:
            body = _digits(_file_text(path, cache))
            found = re.search(rf"(?<![\d.]){re.escape(value)}(?!\d)", body) is not None
        numbers.append(
            {
                "metric": match.group("metric").strip(),
                "value": value,
                "checkable": path is not None,
                "found": found,
            }
        )
    parsed_quotes = [row for row in evidence if row["parsed"]]
    flags = {
        "unparsed_evidence": sum(1 for row in evidence if not row["parsed"]),
        "unresolved_path": sum(1 for row in parsed_quotes if not row["resolves"]),
        "quote_not_found": sum(
            1 for row in parsed_quotes if row["resolves"] and not row["quote_found"]
        ),
        "number_not_found": sum(1 for row in numbers if row["checkable"] and not row["found"]),
        "uncheckable_number": sum(1 for row in numbers if not row["checkable"]),
    }
    future_years = sorted({int(y) for y in _YEAR_RE.findall(raw) if int(y) > as_of.year})
    return {
        "evidence_count": len(evidence),
        "evidence_filing_body": sum(1 for row in evidence if row.get("filing_body")),
        "quotes_found": sum(1 for row in evidence if row["quote_found"]),
        "quote_resolution_rate": (
            round(sum(1 for row in evidence if row["quote_found"]) / len(evidence), 3)
            if evidence
            else 0.0
        ),
        "numbers_count": len(numbers),
        "numbers_found": sum(1 for row in numbers if row["found"]),
        "thesis_breaks": [line.lstrip("-* ").strip() for line in sections["thesis_breaks"]],
        "hallucination_flags": flags,
        "hallucination_flag_total": sum(
            flags[key] for key in ("unresolved_path", "quote_not_found", "number_not_found")
        ),
        "future_year_mentions": future_years,
        "chars": len(raw),
        "words": len(raw.split()),
        "evidence": evidence,
        "numbers": numbers,
    }


def book_effect(verdict: str | None, signal: str | None) -> str:
    """``blocks`` when the book's ``core_sell_reason`` would fail this verdict."""
    from value_investor.core_sell_trigger import core_sell_reason

    if not verdict:
        return "missing"
    return (
        "blocks"
        if core_sell_reason({"signal": signal or "buy", "research_verdict": verdict})
        else "allows"
    )


# --- generation ------------------------------------------------------------

MemoRunner = Callable[..., Any]


def default_runner(
    *,
    report: Any,
    sources_dir: Path,
    model: str,
    api_key: str,
    cwd: str,
    as_of_date: str,
    capture: dict[str, Any],
) -> Any:
    from value_investor.research.agent import run_initial_research_agent

    doc, _agent_id = run_initial_research_agent(
        report=report,
        sources_dir=sources_dir,
        api_key=api_key,
        model=model,
        cwd=cwd,
        job="memo_model_comparison",
        pool=SPEND_POOL_WEEKLY_OPS,
        as_of_date=as_of_date,
        prompt_appendix=COMPARISON_APPENDIX,
        capture=capture,
    )
    return doc


def runtime_models(api_key: str) -> list[str]:
    from value_investor.verify_key import verify_cursor_api_key

    result = verify_cursor_api_key(api_key, list_models=True)
    if not result.ok:
        raise RuntimeError(f"model list unavailable: {result.detail}")
    return [model.id for model in result.models]


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _report_for(entry: dict[str, Any], repo_root: Path) -> Any:
    from value_investor.strategy_book_signals import (
        history_dir_for,
        newest_screen_run,
        repo_paths,
        screen_rows,
    )
    from value_investor.summary import CompanyReport

    paths = repo_paths(repo_root)
    session = date.fromisoformat(entry["session"])
    _path, payload, _day = newest_screen_run(history_dir_for(paths, entry["market"]), session)
    row = dict(screen_rows(payload).get(entry["ticker"]) or {})
    return CompanyReport.from_dict(
        {
            **row,
            "ticker": entry["ticker"],
            "name": row.get("name") or entry["name"],
            "signal": entry["signal"],
        }
    )


def _sources_for(entry: dict[str, Any], repo_root: Path) -> Path:
    from value_investor.strategy_book_signals import repo_paths, research_root_for

    return research_root_for(repo_paths(repo_root), entry["market"]) / entry["ticker"] / "sources"


def _memo_cost(capture: dict[str, Any], estimate: float) -> dict[str, Any]:
    usage = capture.get("usage") if isinstance(capture.get("usage"), dict) else {}
    charged = usage.get("charged_cents")
    return {
        "estimated_usd": estimate,
        "charged_usd": round(float(charged) / 100.0, 4)
        if isinstance(charged, (int, float))
        else None,
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "latency_seconds": capture.get("latency_seconds"),
    }


def run_generation(
    repo_root: Path,
    *,
    now: datetime | None = None,
    api_key: str | None = None,
    runner: MemoRunner | None = None,
    list_models: Callable[[], list[str]] | None = None,
    budget_status: Callable[[], dict[str, Any]] | None = None,
    record_spend: Callable[[float], Any] | None = None,
) -> dict[str, Any]:
    """Generate the missing memos for every manifest name; idempotent on rerun."""
    root = Path(repo_root)
    store = store_dir(root)
    manifest = load_json(store / "manifest.json")
    if manifest is None:
        raise FileNotFoundError(f"{store / 'manifest.json'} missing; run select first")
    moment = now or datetime.now(UTC)
    status = load_json(store / "status.json") or _initial_status(manifest, moment)
    status["generated_at"] = moment.isoformat()
    status["last_run_at"] = moment.isoformat()
    status["errors"] = []
    status.pop("budget_stop", None)
    models = (manifest["models"]["incumbent"], manifest["models"]["challenger"])

    try:
        available = (list_models or (lambda: runtime_models(api_key or "")))()
    except Exception as exc:  # noqa: BLE001 — fail closed, no model call
        status["errors"].append(f"model check failed: {exc}")
        return _persist_status(store, status)
    status["runtime_models"] = {
        "checked_at": moment.isoformat(),
        "grok_ids": sorted(m for m in available if m.startswith("grok-")),
        "incumbent_available": models[0] in available,
        "challenger_available": models[1] in available,
    }
    missing = [model for model in models if model not in available]
    if missing:
        status["errors"].append(f"model not available to this key: {', '.join(missing)}")
        return _persist_status(store, status)

    call = runner or default_runner
    budget = budget_status or (
        lambda: weekly_ops_budget_status(estimated_memo_usd=INCUMBENT_MEMO_USD)
    )
    spend = record_spend or (
        lambda amount: record_estimated_spend(amount, pool=SPEND_POOL_WEEKLY_OPS)
    )
    as_of = status.setdefault("as_of", moment.date().isoformat())
    key = load_json(store / "blind_key.json") or {
        "comparison_id": manifest["comparison_id"],
        "names": {},
    }
    budget_stop: dict[str, str] | None = None

    for entry in manifest["names"]:
        slug = entry["slug"]
        labels = key["names"].setdefault(slug, blind_labels(manifest["comparison_id"], slug))
        pair = status["pairs"].setdefault(slug, {"memos": {}, "attempts": {}})
        if _pair_done(pair) or _pair_exhausted(pair):
            continue
        if budget_stop:
            continue
        snap_dir = work_dir(root) / slug / "sources"
        inputs = snapshot_sources(_sources_for(entry, root), snap_dir)
        if pair.get("inputs") and pair["inputs"]["sha256"] != inputs["sha256"]:
            # One model saw different files; both memos are regenerated.
            pair["superseded"] = [*pair.get("superseded", []), pair["inputs"]]
            pair["memos"] = {}
            pair["attempts"] = {}
            for label in ("A", "B"):
                (store / "memos" / slug / f"{label}.json").unlink(missing_ok=True)
        pair["inputs"] = inputs
        report = _report_for(entry, root)
        for label in ("A", "B"):
            if pair["memos"].get(label, {}).get("ok"):
                continue
            if int(pair["attempts"].get(label) or 0) >= MAX_ATTEMPTS:
                continue
            model = labels[label]
            estimate = estimated_memo_usd(model)
            spent = float(status["spend"]["estimated_usd"])
            if spent + estimate > BUDGET_CAP_USD:
                budget_stop = {
                    "kind": "cap",
                    "detail": f"comparison cap ${BUDGET_CAP_USD:.2f} reached at ${spent:.2f}",
                }
                break
            remaining = float((budget() or {}).get("remaining_weekly_ops_usd") or 0.0)
            if remaining - estimate < STRATEGY_BOOK_RESERVE_USD:
                budget_stop = {
                    "kind": "weekly_headroom",
                    "detail": (
                        f"weekly_ops headroom ${remaining:.2f} would fall below the "
                        f"${STRATEGY_BOOK_RESERVE_USD:.2f} strategy-book reserve"
                    ),
                }
                break
            pair["attempts"][label] = int(pair["attempts"].get(label) or 0) + 1
            capture: dict[str, Any] = {}
            record: dict[str, Any] = {
                "label": label,
                "slug": slug,
                "as_of": as_of,
                "inputs": inputs,
            }
            try:
                doc = call(
                    report=report,
                    sources_dir=snap_dir.resolve(),
                    model=model,
                    api_key=api_key or "",
                    cwd=str(snap_dir.parent.resolve()),
                    as_of_date=as_of,
                    capture=capture,
                )
            except Exception as exc:  # noqa: BLE001 — logged; a later run may retry once
                record.update({"ok": False, "error": str(exc)[:500]})
                status["errors"].append(f"{slug} {label}: {str(exc)[:200]}")
            else:
                raw = str(capture.get("raw_text") or "")
                verdict = getattr(doc, "research_verdict", None)
                record.update(
                    {
                        "ok": True,
                        "verdict": verdict,
                        "risk": getattr(doc, "research_risk_level", None),
                        "confidence": getattr(doc, "research_confidence", None),
                        "rationale": getattr(doc, "research_rationale", None),
                        "risk_tags": list(getattr(doc, "risk_tags", None) or []),
                        "book_effect": book_effect(verdict, entry.get("signal")),
                        "raw_text": raw,
                        "checks": score_memo(
                            raw, sources_dir=snap_dir, as_of=date.fromisoformat(as_of)
                        ),
                    }
                )
            if capture.get("prompt"):
                status["prompt_sha256"].setdefault(
                    slug, hashlib.sha256(str(capture["prompt"]).encode("utf-8")).hexdigest()
                )
            cost = _memo_cost(capture, estimate)
            spend(estimate)
            status["spend"]["estimated_usd"] = round(spent + estimate, 2)
            status["spend"]["memos_called"] = int(status["spend"]["memos_called"]) + 1
            # Model-specific cost and timing stay out of the blinded memo file.
            pair.setdefault("cost", {})[label] = cost
            write_json(store / "memos" / slug / f"{label}.json", record, compact=False)
            pair["memos"][label] = {"ok": bool(record.get("ok")), "at": moment.isoformat()}

    write_json(store / "blind_key.json", key, compact=False)
    if budget_stop:
        status["errors"].append(f"stopped: {budget_stop['detail']}")
        status["budget_stop"] = budget_stop
    order = [entry["slug"] for entry in manifest["names"]]
    pairs = status["pairs"]
    complete = [slug for slug in order if slug in pairs and _pair_done(pairs[slug])]
    exhausted = [slug for slug in order if slug in pairs and _pair_exhausted(pairs[slug])]
    status["complete_pairs"] = len(complete)
    status["exhausted_pairs"] = exhausted
    finished = len(complete) + len(exhausted) == len(manifest["names"])
    if finished and complete:
        results = build_results(root, manifest, status, key)
        write_json(store / "results.json", results, compact=False)
        (store / "review.md").write_text(render_review(root, manifest, complete), encoding="utf-8")
        write_json(
            store / "ratings_template.json", ratings_template(manifest, complete), compact=False
        )
        if status.get("state") != STATE_READY:
            status["ready_at"] = moment.isoformat()
        status["state"] = STATE_READY
    else:
        status["state"] = STATE_INCOMPLETE if status["pairs"] else STATE_SELECTED
    return _persist_status(store, status)


def _pair_done(pair: dict[str, Any]) -> bool:
    return all((pair.get("memos") or {}).get(label, {}).get("ok") for label in ("A", "B"))


def _pair_exhausted(pair: dict[str, Any]) -> bool:
    """Not done, and every missing memo has used its attempts."""
    if _pair_done(pair):
        return False
    memos = pair.get("memos") or {}
    attempts = pair.get("attempts") or {}
    return all(
        int(attempts.get(label) or 0) >= MAX_ATTEMPTS
        for label in ("A", "B")
        if not memos.get(label, {}).get("ok")
    )


def _initial_status(manifest: dict[str, Any], moment: datetime) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "comparison_id": manifest["comparison_id"],
        "generated_at": moment.isoformat(),
        "state": STATE_SELECTED,
        "names": len(manifest["names"]),
        "pairs": {},
        "prompt_sha256": {},
        "spend": {"estimated_usd": 0.0, "memos_called": 0, "cap_usd": BUDGET_CAP_USD},
        "errors": [],
        "observe_only": True,
        "influences_live": False,
    }


def _persist_status(store: Path, status: dict[str, Any]) -> dict[str, Any]:
    write_json(store / "status.json", status, compact=False)
    return status


# --- results, blind review, ratings ---------------------------------------


def _memo(root: Path, slug: str, label: str) -> dict[str, Any]:
    return load_json(store_dir(root) / "memos" / slug / f"{label}.json") or {}


def build_results(
    root: Path, manifest: dict[str, Any], status: dict[str, Any], key: dict[str, Any]
) -> dict[str, Any]:
    """Unblinded automated comparison. Rate the review before reading this."""
    per_name: list[dict[str, Any]] = []
    by_model: dict[str, list[dict[str, Any]]] = {m: [] for m in manifest["models"].values()}
    for entry in manifest["names"]:
        slug = entry["slug"]
        pair = status["pairs"].get(slug) or {}
        if not all(pair.get("memos", {}).get(label, {}).get("ok") for label in ("A", "B")):
            continue
        labels = key["names"][slug]
        rows = {}
        for label in ("A", "B"):
            memo = _memo(root, slug, label)
            model = labels[label]
            row = {
                "model": model,
                "verdict": memo.get("verdict"),
                "risk": memo.get("risk"),
                "confidence": memo.get("confidence"),
                "book_effect": memo.get("book_effect"),
                **{
                    k: v
                    for k, v in (memo.get("checks") or {}).items()
                    if k not in {"evidence", "numbers"}
                },
                **(pair.get("cost", {}).get(label) or {}),
            }
            rows[model] = row
            by_model[model].append(row)
        inc, chal = (rows[manifest["models"]["incumbent"]], rows[manifest["models"]["challenger"]])
        per_name.append(
            {
                "slug": slug,
                "market": entry["market"],
                "ticker": entry["ticker"],
                "bucket": entry["bucket"],
                "verdict_agree": inc["verdict"] == chal["verdict"],
                "book_effect_agree": inc["book_effect"] == chal["book_effect"],
                "incumbent": inc,
                "challenger": chal,
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "comparison_id": manifest["comparison_id"],
        "generated_at": status["generated_at"],
        "models": manifest["models"],
        "names": per_name,
        "verdict_agreement": _share(per_name, "verdict_agree"),
        "book_effect_agreement": _share(per_name, "book_effect_agree"),
        "by_model": {model: _aggregate(rows) for model, rows in by_model.items()},
        "spend": status["spend"],
        "observe_only": True,
        "influences_live": False,
    }


def _share(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    hits = sum(1 for row in rows if row[key])
    return {"agree": hits, "of": len(rows), "share": round(hits / len(rows), 3) if rows else None}


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"memos": 0}

    def total(name: str) -> int:
        return sum(int(row.get(name) or 0) for row in rows)

    charged = [
        row["charged_usd"] for row in rows if isinstance(row.get("charged_usd"), (int, float))
    ]
    latency = [
        row["latency_seconds"]
        for row in rows
        if isinstance(row.get("latency_seconds"), (int, float))
    ]
    tokens = [row["total_tokens"] for row in rows if isinstance(row.get("total_tokens"), int)]
    evidence = total("evidence_count")
    return {
        "memos": len(rows),
        "evidence_count": evidence,
        "evidence_filing_body": total("evidence_filing_body"),
        "quotes_found": total("quotes_found"),
        "quote_resolution_rate": round(total("quotes_found") / evidence, 3) if evidence else 0.0,
        "numbers_count": total("numbers_count"),
        "numbers_found": total("numbers_found"),
        "hallucination_flag_total": total("hallucination_flag_total"),
        "thesis_breaks_mean": round(mean(len(row.get("thesis_breaks") or []) for row in rows), 2),
        "words_mean": round(mean(int(row.get("words") or 0) for row in rows), 1),
        "verdicts": _counts(row.get("verdict") for row in rows),
        "blocks": sum(1 for row in rows if row.get("book_effect") == "blocks"),
        "estimated_usd": round(sum(float(row.get("estimated_usd") or 0) for row in rows), 2),
        "charged_usd": round(sum(charged), 4) if charged else None,
        "charged_usd_per_memo": round(sum(charged) / len(charged), 4) if charged else None,
        "total_tokens_mean": round(mean(tokens), 1) if tokens else None,
        "latency_seconds_median": round(median(latency), 1) if latency else None,
    }


def _counts(values: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        out[str(value)] = out.get(str(value), 0) + 1
    return out


def _memo_block(memo: dict[str, Any]) -> list[str]:
    checks = memo.get("checks") or {}
    sections = parse_appendix(str(memo.get("raw_text") or ""))
    lines = [
        f"- **Verdict:** {memo.get('verdict')} · **Risk:** {memo.get('risk')} · "
        f"**Confidence:** {memo.get('confidence')}",
        f"- **Rationale:** {memo.get('rationale') or '_(none)_'}",
        f"- **Risk tags:** {', '.join(memo.get('risk_tags') or []) or '_(none)_'}",
        "",
        "Evidence:",
        *(sections["evidence"] or ["- _(none)_"]),
        "",
        "Numbers:",
        *(sections["numbers"] or ["- _(none)_"]),
        "",
        "Thesis breaks:",
        *([f"- {item}" for item in checks.get("thesis_breaks") or []] or ["- _(none)_"]),
    ]
    return lines


def render_review(root: Path, manifest: dict[str, Any], complete: list[str]) -> str:
    """Blind side-by-side doc. Model names, cost and timing are left out."""
    lines = [
        "# Memo model comparison — blind owner review",
        "",
        f"Comparison `{manifest['comparison_id']}`. Each name has two memos, **A** and **B**, written "
        "by two different models from the same frozen filing bodies, the same prompt and the "
        "same as-of date. Which model wrote which is in `blind_key.json`; do not open it, "
        "`results.json` or the `memos/` cost fields until every name is rated.",
        "",
        "Rate each memo 1 (poor) to 5 (excellent) on:",
        "",
        *[f"- `{key}` — {text}" for key, text in RUBRIC.items()],
        "",
        "Then pick `preferred`: `A`, `B` or `tie` — which memo you would rather the strategy "
        "book act on. Copy `ratings_template.json` to `ratings.json` in this folder, fill it "
        "in and commit it to main. Automation never writes `ratings.json`.",
        "",
    ]
    by_slug = {entry["slug"]: entry for entry in manifest["names"]}
    for index, slug in enumerate(complete, start=1):
        entry = by_slug[slug]
        lines.extend(
            [
                f"## {index}. {entry['name']} ({entry['ticker']}) — {entry['market']}",
                "",
                f"Screen `{entry['signal']}` on {entry['session']}; operating decline "
                f"`{entry['decline_verdict']}`, sector `{entry['sector_verdict']}`; "
                f"RSI {entry['rsi_14']}; {entry['filings_with_body']} filing bodies. "
                f"Ratings key: `{slug}`.",
                "",
            ]
        )
        for label in ("A", "B"):
            lines.extend([f"### Memo {label}", "", *_memo_block(_memo(root, slug, label)), ""])
    return "\n".join(lines).rstrip() + "\n"


def ratings_template(manifest: dict[str, Any], complete: list[str]) -> dict[str, Any]:
    blank = {key: None for key in RUBRIC}
    return {
        "schema_version": SCHEMA_VERSION,
        "comparison_id": manifest["comparison_id"],
        "rater": None,
        "rated_at": None,
        "scale": "1 (poor) to 5 (excellent); preferred is A, B or tie",
        "names": {
            slug: {"preferred": None, "A": dict(blank), "B": dict(blank), "note": ""}
            for slug in complete
        },
    }


def ratings_progress(ratings: dict[str, Any] | None) -> tuple[int, int]:
    names = (ratings or {}).get("names") or {}
    done = 0
    for row in names.values():
        if not isinstance(row, dict) or row.get("preferred") not in {"A", "B", "tie"}:
            continue
        scores = [row.get(label, {}).get(key) for label in ("A", "B") for key in RUBRIC]
        if all(isinstance(value, int) and 1 <= value <= 5 for value in scores):
            done += 1
    return done, len(names)


# --- decision rule ---------------------------------------------------------

MIN_COMPLETE_PAIRS = 10
MIN_CHALLENGER_PREFERRED = 8
MAX_INCUMBENT_PREFERRED = 3
MIN_RUBRIC_GAIN = 1.0
WEEKLY_MEMO_HIGH = 35
STRATEGY_BOOK_MEMO_RAISE_USD = 40.0


def decide(
    manifest: dict[str, Any],
    results: dict[str, Any],
    ratings: dict[str, Any],
    key: dict[str, Any],
) -> dict[str, Any]:
    """Apply the pre-declared rule. Reports only; nothing is switched."""
    incumbent = manifest["models"]["incumbent"]
    challenger = manifest["models"]["challenger"]
    prefs = {"challenger": 0, "incumbent": 0, "tie": 0}
    gains: list[float] = []
    disagreements = {"challenger": 0, "incumbent": 0, "tie": 0}
    effect_disagree = {
        row["slug"] for row in results.get("names") or [] if not row["book_effect_agree"]
    }
    for slug, row in (ratings.get("names") or {}).items():
        labels = key["names"].get(slug) or {}
        side = {labels.get("A"): "A", labels.get("B"): "B"}
        pick = row.get("preferred")
        winner = (
            "tie"
            if pick == "tie"
            else ("challenger" if labels.get(pick) == challenger else "incumbent")
        )
        prefs[winner] += 1
        if slug in effect_disagree:
            disagreements[winner] += 1
        totals = {
            model: sum(int(row.get(side[model], {}).get(k) or 0) for k in RUBRIC)
            for model in (incumbent, challenger)
        }
        gains.append(totals[challenger] - totals[incumbent])
    agg = results.get("by_model") or {}
    inc, chal = agg.get(incumbent) or {}, agg.get(challenger) or {}
    per_memo = chal.get("charged_usd_per_memo") or estimated_memo_usd(challenger)
    weekly = round(per_memo * WEEKLY_MEMO_HIGH, 2)
    complete = len(results.get("names") or [])
    checks = {
        "complete_pairs": {
            "value": complete,
            "need": f">= {MIN_COMPLETE_PAIRS}",
            "ok": complete >= MIN_COMPLETE_PAIRS,
        },
        "owner_prefers_challenger": {
            "value": prefs,
            "need": f"challenger >= {MIN_CHALLENGER_PREFERRED} and incumbent <= {MAX_INCUMBENT_PREFERRED}",
            "ok": prefs["challenger"] >= MIN_CHALLENGER_PREFERRED
            and prefs["incumbent"] <= MAX_INCUMBENT_PREFERRED,
        },
        "rubric_gain": {
            "value": round(mean(gains), 2) if gains else None,
            "need": f"mean challenger minus incumbent total (of 15) >= {MIN_RUBRIC_GAIN}",
            "ok": bool(gains) and mean(gains) >= MIN_RUBRIC_GAIN,
        },
        "citations_not_worse": {
            "value": {
                "incumbent": inc.get("quote_resolution_rate"),
                "challenger": chal.get("quote_resolution_rate"),
            },
            "need": "challenger quote resolution rate >= incumbent",
            "ok": float(chal.get("quote_resolution_rate") or 0)
            >= float(inc.get("quote_resolution_rate") or 0),
        },
        "hallucination_not_worse": {
            "value": {
                "incumbent": inc.get("hallucination_flag_total"),
                "challenger": chal.get("hallucination_flag_total"),
            },
            "need": "challenger hallucination flags <= incumbent",
            "ok": int(chal.get("hallucination_flag_total") or 0)
            <= int(inc.get("hallucination_flag_total") or 0),
        },
        "book_effect_disagreements": {
            "value": disagreements,
            "need": "where the two verdicts differ on blocking entry, owner prefers challenger at least as often",
            "ok": disagreements["challenger"] >= disagreements["incumbent"],
        },
        "weekly_cost_fits": {
            "value": {"per_memo_usd": per_memo, "weekly_high_usd": weekly},
            "need": f"{WEEKLY_MEMO_HIGH} memos a week <= ${STRATEGY_BOOK_MEMO_RAISE_USD:.0f} strategy_book_memo_raise",
            "ok": weekly <= STRATEGY_BOOK_MEMO_RAISE_USD,
        },
    }
    if all(row["ok"] for row in checks.values()):
        outcome = "switch"
    elif complete >= MIN_COMPLETE_PAIRS and (
        prefs["incumbent"] >= prefs["challenger"] or not checks["hallucination_not_worse"]["ok"]
    ):
        outcome = "keep"
    else:
        outcome = "inconclusive_keep"
    return {
        "comparison_id": manifest["comparison_id"],
        "outcome": outcome,
        "checks": checks,
        "incumbent": incumbent,
        "challenger": challenger,
        "note": (
            "switch: owner approves, then the memo model change is logged as an "
            "operational_switches row on docs/data/strategy_book_registration.json "
            "(not a rule change) and the memo runner's model is changed in its own PR. "
            "keep / inconclusive_keep: composer-2.5 stays; nothing changes."
        ),
        "observe_only": True,
        "influences_live": False,
    }


# --- ops findings ----------------------------------------------------------


def _finding(severity: str, title: str, summary: str) -> dict[str, Any]:
    return {
        "severity": severity,
        "category": "research",
        "title": title,
        "summary": summary,
        "auto_fixable": False,
    }


def findings(repo_root: Path, now: datetime | None = None) -> list[dict[str, Any]]:
    """Read-only lifecycle findings. Never auto-fixable; no rememo or ingest."""
    moment = now or datetime.now(UTC)
    store = store_dir(Path(repo_root))
    manifest = load_json(store / "manifest.json")
    if manifest is None:
        return [_finding("warn", TITLE_FAILED, f"{STORE_REL}/manifest.json missing or unreadable.")]
    status = load_json(store / "status.json")
    names = len(manifest.get("names") or [])
    est = (manifest.get("budget") or {}).get("estimated_total_usd")
    dispatch = "gh workflow run memo-model-comparison.yml -f action=generate"
    if status is None:
        return [
            _finding(
                "info",
                TITLE_AWAITING,
                f"{names} names selected ({RULE_VERSION}); estimated ${est} of a "
                f"${BUDGET_CAP_USD:.2f} cap. Runs on the next scheduled slot or `{dispatch}`.",
            )
        ]
    out: list[dict[str, Any]] = []
    if status.get("errors"):
        out.append(
            _finding(
                "warn",
                TITLE_FAILED,
                f"State {status.get('state')}; {status.get('complete_pairs', 0)}/{names} pairs. "
                + "; ".join(str(e) for e in status["errors"][:4]),
            )
        )
    if status.get("state") != STATE_READY:
        if not out:
            out.append(
                _finding(
                    "info",
                    TITLE_AWAITING,
                    f"State {status.get('state')}; {status.get('complete_pairs', 0)}/{names} pairs; "
                    f"spent ${status.get('spend', {}).get('estimated_usd')}. `{dispatch}`.",
                )
            )
        return out
    ratings = load_json(store / "ratings.json")
    done, total = ratings_progress(ratings or load_json(store / "ratings_template.json"))
    if total and done == total:
        results = load_json(store / "results.json") or {}
        key = load_json(store / "blind_key.json") or {"names": {}}
        verdict = decide(manifest, results, ratings or {}, key)
        failed = [name for name, row in verdict["checks"].items() if not row["ok"]]
        out.append(
            _finding(
                "info",
                TITLE_DECIDED,
                f"Outcome {verdict['outcome']} ({verdict['incumbent']} vs {verdict['challenger']}); "
                f"failed checks: {', '.join(failed) or 'none'}. A switch needs owner approval and an "
                "operational_switches row on the registration. Observe-only.",
            )
        )
        return out
    ready_raw = str(status.get("ready_at") or status.get("generated_at") or "")
    try:
        ready = datetime.fromisoformat(ready_raw.replace("Z", "+00:00"))
    except ValueError:
        ready = moment
    if ready.tzinfo is None:
        ready = ready.replace(tzinfo=UTC)
    age = (moment - ready).days
    severity, title = ("warn", TITLE_STALE) if age > REVIEW_STALE_DAYS else ("info", TITLE_READY)
    out.append(
        _finding(
            severity,
            title,
            f"{done}/{total} names rated; ready {age} days. Read {STORE_REL}/review.md, copy "
            "ratings_template.json to ratings.json and fill it (human task "
            "adhoc-memo-model-comparison-blind-review). Observe-only.",
        )
    )
    return out


def json_dumps(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, default=str)


def due_for_generation(repo_root: Path) -> bool:
    """True while some pair still has attempts left and no budget stop is recorded."""
    store = store_dir(Path(repo_root))
    manifest = load_json(store / "manifest.json")
    if manifest is None:
        return False
    status = load_json(store / "status.json")
    if status is None:
        return True
    if status.get("state") == STATE_READY:
        return False
    stop = status.get("budget_stop") or {}
    return stop.get("kind") != "cap"


__all__ = [
    "BUDGET_CAP_USD",
    "CHALLENGER_MODEL",
    "COMPARISON_APPENDIX",
    "INCUMBENT_MODEL",
    "SELECTION_RULE",
    "TITLE_AWAITING",
    "TITLE_DECIDED",
    "TITLE_FAILED",
    "TITLE_READY",
    "TITLE_STALE",
    "book_effect",
    "decide",
    "due_for_generation",
    "findings",
    "run_generation",
    "score_memo",
    "select_names",
    "strongest_configured_grok",
]
