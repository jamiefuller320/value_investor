"""Side-by-side memo model comparison (owner, 2026-11-10). Observe-only.

Incumbent ``composer-2.5`` against the strongest Grok configured in
``agent_model_policy`` on a fixed set of names. Both memos for a name read one
frozen copy of that name's research sources, the same production prompt (plus
one comparison appendix asking for checkable evidence), and the same as-of
date. Everything is written under ``docs/data/memo_model_comparison/``. Nothing
here writes the research store, the memo log, the strategy book or any
decision path, and the strategy-book memo job is not imported for its runner.

Rule v2 (owner, 2026-11-10, amended before any memo existed): a judge from a
third model family scores every pair blind in both orders, and the owner rates
only a calibration sample. Generation refuses a manifest without rule v2.

Runbook and the pre-declared decision rule: docs/ops/memo-model-comparison.md.
"""

from __future__ import annotations

import hashlib
import json
import math
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
TITLE_AWAITING_JUDGE = "Memo model comparison awaiting judge"
TITLE_READY = "Memo model comparison ready for owner calibration"
TITLE_STALE = "Memo model comparison owner calibration stale"
TITLE_DECIDED = "Memo model comparison decided"
TITLE_FAILED = "Memo model comparison failed"

STATE_SELECTED = "selected"
STATE_INCOMPLETE = "incomplete"
STATE_GENERATED = "awaiting_judge"
JUDGE_STATE_INCOMPLETE = "incomplete"
JUDGE_STATE_DONE = "ready_for_calibration"

# --- rule v2 amendment (owner, 2026-11-10) ----------------------------------

DECISION_RULE_VERSION = "v2"
AMENDED_ON = "2026-11-10"
OWNER_QUOTE = "yes please"
AMENDMENT_DOC = "docs/ops/memo-model-comparison.md#amendment-rule-v2-2026-11-10"

# Strongest third-family model that both answered the CURSOR_API_KEY_V2 model
# list on 2026-11-10 and has a rate in agent_model_policy.MODEL_API_RATES.
JUDGE_MODEL = "gpt-5.6-luna"
JUDGE_ORDERS = ("AB", "BA")
JUDGE_MAX_ATTEMPTS = 2
# 12 pairs x 2 orders x $0.94 = $22.56 estimated, capped here.
JUDGE_BUDGET_CAP_USD = 28.0
JUDGE_QUOTES_PER_SCORE = 1
BARRED_JUDGE_FAMILIES = frozenset({"cursor", "xai"})

CALIBRATION_MIN_SAMPLE = 4
CALIBRATION_AGREE_FRACTION = 0.75

_FAMILY_PREFIXES = (
    ("composer", "cursor"),
    ("default", "cursor"),
    ("cursor", "cursor"),
    ("grok", "xai"),
    ("gpt", "openai"),
    ("o1", "openai"),
    ("o3", "openai"),
    ("o4", "openai"),
    ("claude", "anthropic"),
    ("gemini", "google"),
    ("kimi", "moonshot"),
    ("glm", "zhipu"),
    ("deepseek", "deepseek"),
)
_REDACT_RE = re.compile(
    r"\b(?:composer|cursor|grok|xai|x\.ai|gpt|openai|claude|anthropic|gemini)[\w.-]*",
    re.IGNORECASE,
)

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


def estimated_judge_usd(names: int, judge: str = JUDGE_MODEL) -> float:
    """One judge call per order per pair, each priced like one memo on that model."""
    return round(names * len(JUDGE_ORDERS) * estimated_memo_usd(judge), 2)


def model_family(model_id: str) -> str:
    text = model_id.strip().lower()
    for prefix, family in _FAMILY_PREFIXES:
        if text.startswith(prefix):
            return family
    return "unknown"


def check_judge_model(
    judge: str,
    models: dict[str, str],
    *,
    rates: dict[str, Any] | None = None,
    available: list[str] | None = None,
) -> None:
    """Raise unless ``judge`` is a third family with a rate (and, if given, available)."""
    family = model_family(judge)
    compared = {model_family(m) for m in models.values()}
    if family == "unknown":
        raise ValueError(f"judge {judge} has no known model family")
    if family in BARRED_JUDGE_FAMILIES or family in compared:
        raise ValueError(
            f"judge {judge} is family {family}; it must differ from "
            f"{sorted(compared | BARRED_JUDGE_FAMILIES)}"
        )
    if judge not in (rates if rates is not None else MODEL_API_RATES):
        raise ValueError(f"judge {judge} has no rate in agent_model_policy.MODEL_API_RATES")
    if available is not None and judge not in available:
        raise ValueError(f"judge {judge} not available to this key")


def calibration_need(sample: int) -> int:
    """Owner-judge agreements required on a calibration sample of ``sample`` pairs."""
    return math.ceil(CALIBRATION_AGREE_FRACTION * sample)


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


def amend_rule_v2(manifest: dict[str, Any], *, store: Path) -> dict[str, Any]:
    """Add the rule v2 judge amendment. Refuses once any generation output exists."""
    existing = [
        name
        for name in ("status.json", "results.json", "memos", "review.md")
        if (store / name).exists()
    ]
    if existing:
        raise ValueError(f"generation output exists ({', '.join(existing)}); cannot amend")
    if manifest.get("decision_rule_version") == DECISION_RULE_VERSION:
        return manifest
    check_judge_model(JUDGE_MODEL, manifest["models"])
    names = len(manifest["names"])
    per_call = estimated_memo_usd(JUDGE_MODEL)
    judge_total = estimated_judge_usd(names)
    budget = dict(manifest.get("budget") or {})
    budget.update(
        {
            "judge_cap_usd": JUDGE_BUDGET_CAP_USD,
            "judge_estimated_usd_per_call": per_call,
            "judge_estimated_total_usd": judge_total,
            "comparison_cap_usd": round(
                float(budget.get("cap_usd") or 0) + JUDGE_BUDGET_CAP_USD, 2
            ),
            "comparison_estimated_total_usd": round(
                float(budget.get("estimated_total_usd") or 0) + judge_total, 2
            ),
        }
    )
    return {
        **manifest,
        "decision_rule_version": DECISION_RULE_VERSION,
        "amendment": {
            "rule": DECISION_RULE_VERSION,
            "amended_on": AMENDED_ON,
            "owner_quote": OWNER_QUOTE,
            "owner_decision": (
                "Add an LLM judge from a third model family that scores every pair blind in "
                "both orders; the owner rates only a calibration sample."
            ),
            "before_any_results": True,
            "generation_state_at_amendment": (
                "never run: no status.json, memos, results.json or review.md existed"
            ),
            "selection_unchanged": True,
            "doc": AMENDMENT_DOC,
        },
        "judge": {
            "model": JUDGE_MODEL,
            "family": model_family(JUDGE_MODEL),
            "orders": list(JUDGE_ORDERS),
            "rubric": list(RUBRIC),
            "max_attempts": JUDGE_MAX_ATTEMPTS,
            "calls": names * len(JUDGE_ORDERS),
        },
        "budget": budget,
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
    return snapshot_digest(dest)


def snapshot_digest(dest: Path) -> dict[str, Any]:
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
    if manifest.get("decision_rule_version") != DECISION_RULE_VERSION:
        status["errors"].append(
            f"manifest decision rule {manifest.get('decision_rule_version') or 'v1'} is not "
            f"{DECISION_RULE_VERSION}; generation refuses until the judge amendment is recorded"
        )
        return _persist_status(store, status)

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
        if status.get("state") != STATE_GENERATED:
            status["generation_done_at"] = moment.isoformat()
        status["state"] = STATE_GENERATED
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
    """Blind side-by-side doc for the calibration sample. Model names, cost, timing,
    the judge's scores and the reason a name was sampled are left out."""
    lines = [
        "# Memo model comparison — owner calibration sample (blind)",
        "",
        f"Comparison `{manifest['comparison_id']}`, rule {DECISION_RULE_VERSION}. An LLM judge "
        f"has scored every pair; you rate only these {len(complete)} names so the judge can be "
        "checked against you. Each name has two memos, **A** and **B**, written by two "
        "different models from the same frozen filing bodies, the same prompt and the same "
        "as-of date. Do not open `blind_key.json`, `results.json`, `judge_results.json`, "
        "`calibration.json`, `judgements/` or the `status.json` cost fields until every name "
        "here is rated.",
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


# --- judge (rule v2) -------------------------------------------------------

JudgeRunner = Callable[..., str]

_JUDGE_SCHEMA = """{
  "scores": {
    "A": {
      "evidence": {"score": 1-5, "reason": "...", "quotes": [{"source": "memo" or "<path under the sources folder>", "quote": "<verbatim>"}]},
      "thesis_break": {"score": 1-5, "reason": "...", "quotes": [...]},
      "verdict_justified": {"score": 1-5, "reason": "...", "quotes": [...]}
    },
    "B": {same three keys}
  },
  "preferred": "A" | "B" | "tie",
  "preference_reason": "...",
  "claims_checked": [{"memo": "A" | "B", "claim": "...", "path": "...", "supported": true | false}]
}"""


def redact_model_names(text: str) -> tuple[str, int]:
    return _REDACT_RE.subn("[model]", text)


def judge_prompt(
    entry: dict[str, Any],
    memos: dict[str, dict[str, Any]],
    *,
    sources_dir: Path,
    as_of: str,
) -> str:
    """Blind judge prompt. ``memos`` maps the judge-facing label (A, B) to a memo."""
    rubric = "\n".join(f"- {key}: {text}" for key, text in RUBRIC.items())
    blocks = []
    for label in ("A", "B"):
        text, _hits = redact_model_names(str(memos[label].get("raw_text") or ""))
        blocks.append(f"=== MEMO {label} ===\n{text.strip()}\n=== END MEMO {label} ===")
    return f"""You are judging two investment research memos, A and B, on {entry["name"]} \
({entry["ticker"]}, {entry["market"]}). Both were written as of {as_of} from the same source \
files, which are in this folder: {sources_dir}
Open the files the memos cite and check their quotes and numbers against them. Use only those \
files; do not use knowledge from outside them or from after {as_of}.

The memo's verdict decides whether a value strategy may buy the name: pass, sell, avoid or \
exit blocks the entry; any other verdict allows it.

Rate each memo from 1 (poor) to 5 (excellent) on:
{rubric}

Then set preferred to A, B or tie: the memo you would rather the strategy act on. For every \
score give a reason and at least {JUDGE_QUOTES_PER_SCORE} verbatim quote that supports it. A \
quote's source is "memo" when it quotes that memo, or the file's path relative to the sources \
folder when it quotes a source file. List in claims_checked the memo claims you checked \
against a file.

Reply with one JSON object and nothing else, in this shape:
{_JUDGE_SCHEMA}

{blocks[0]}

{blocks[1]}
"""


def parse_judge_output(raw: str) -> tuple[dict[str, Any] | None, list[str]]:
    """First JSON object in ``raw`` and the reasons it fails the schema (empty when valid)."""
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    start = text.find("{")
    if start < 0:
        return None, ["no JSON object"]
    try:
        payload, _end = json.JSONDecoder().raw_decode(text[start:])
    except ValueError as exc:
        return None, [f"invalid JSON: {exc}"]
    if not isinstance(payload, dict):
        return None, ["top level is not an object"]
    problems: list[str] = []
    if payload.get("preferred") not in {"A", "B", "tie"}:
        problems.append("preferred must be A, B or tie")
    scores = payload.get("scores") if isinstance(payload.get("scores"), dict) else {}
    for label in ("A", "B"):
        memo = scores.get(label) if isinstance(scores.get(label), dict) else {}
        for key in RUBRIC:
            row = memo.get(key) if isinstance(memo.get(key), dict) else {}
            score = row.get("score")
            if not (isinstance(score, int) and not isinstance(score, bool) and 1 <= score <= 5):
                problems.append(f"{label}.{key}.score must be an integer 1-5")
            if not str(row.get("reason") or "").strip():
                problems.append(f"{label}.{key}.reason missing")
            quotes = row.get("quotes") if isinstance(row.get("quotes"), list) else []
            usable = [
                q for q in quotes if isinstance(q, dict) and str(q.get("quote") or "").strip()
            ]
            if len(usable) < JUDGE_QUOTES_PER_SCORE:
                problems.append(f"{label}.{key}.quotes needs {JUDGE_QUOTES_PER_SCORE}+")
    return payload, problems


def check_judge_quotes(
    payload: dict[str, Any], memos: dict[str, dict[str, Any]], *, sources_dir: Path
) -> dict[str, Any]:
    """Whether each quote the judge cites appears in the memo or the source file it names."""
    cache: dict[Path, str] = {}
    rows: list[dict[str, Any]] = []
    for label in ("A", "B"):
        memo_text = _normalise(str(memos[label].get("raw_text") or ""))
        for key in RUBRIC:
            for quote in ((payload["scores"][label][key] or {}).get("quotes")) or []:
                if not isinstance(quote, dict):
                    continue
                source = str(quote.get("source") or "memo").strip()
                needle = _normalise(str(quote.get("quote") or ""))
                if source.lower() == "memo":
                    found, resolves = needle in memo_text, True
                else:
                    path = _resolve(sources_dir, source)
                    resolves = path is not None
                    found = bool(path and needle in _normalise(_file_text(path, cache)))
                rows.append(
                    {
                        "label": label,
                        "key": key,
                        "source": source,
                        "resolves": resolves,
                        "found": found,
                    }
                )
    found = sum(1 for row in rows if row["found"])
    return {
        "quotes": len(rows),
        "found": found,
        "found_rate": round(found / len(rows), 3) if rows else 0.0,
        "rows": rows,
    }


def default_judge_runner(
    *, prompt: str, model: str, api_key: str, cwd: str, as_of_date: str, capture: dict[str, Any]
) -> str:
    from value_investor.research.agent import _run_agent_prompt

    text, _agent_id = _run_agent_prompt(
        prompt=prompt,
        api_key=api_key,
        model=model,
        cwd=cwd,
        as_of_date=as_of_date,
        job="memo_model_judge",
        pool=SPEND_POOL_WEEKLY_OPS,
        capture=capture,
    )
    return text


def _order_memos(order: str, memos: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Judge-facing label -> stored memo. ``AB`` shows stored A first; ``BA`` shows B first."""
    return {"A": memos[order[0]], "B": memos[order[1]]}


def _to_stored(order: str, judge_label: str) -> str:
    if judge_label == "tie":
        return "tie"
    return order[0] if judge_label == "A" else order[1]


def _judgement(root: Path, slug: str, order: str) -> dict[str, Any]:
    return load_json(store_dir(root) / "judgements" / slug / f"{order}.json") or {}


def summarise_pair(root: Path, slug: str) -> dict[str, Any] | None:
    """Both orders mapped back to stored labels; ``None`` unless both orders are valid."""
    rows = {order: _judgement(root, slug, order) for order in JUDGE_ORDERS}
    if not all(row.get("ok") for row in rows.values()):
        return None
    picks = {order: _to_stored(order, rows[order]["parsed"]["preferred"]) for order in JUDGE_ORDERS}
    consistent = len(set(picks.values())) == 1
    scores: dict[str, dict[str, float]] = {}
    for stored in ("A", "B"):
        per_key: dict[str, float] = {}
        for key in RUBRIC:
            values = []
            for order in JUDGE_ORDERS:
                judge_label = "A" if order[0] == stored else "B"
                values.append(int(rows[order]["parsed"]["scores"][judge_label][key]["score"]))
            per_key[key] = round(mean(values), 2)
        scores[stored] = {**per_key, "total": round(sum(per_key.values()), 2)}
    return {
        "slug": slug,
        "picks_by_order": picks,
        "order_consistent": consistent,
        "preferred": picks[JUDGE_ORDERS[0]] if consistent else "tie",
        "scores": scores,
        "judge_quote_found_rate": {
            order: rows[order].get("quote_check", {}).get("found_rate") for order in JUDGE_ORDERS
        },
    }


def mechanical_direction(memo_a: dict[str, Any], memo_b: dict[str, Any]) -> str:
    """Label the automated checks favour: fewer hallucination flags, then higher quote resolution."""
    ca, cb = memo_a.get("checks") or {}, memo_b.get("checks") or {}
    fa, fb = (
        int(ca.get("hallucination_flag_total") or 0),
        int(cb.get("hallucination_flag_total") or 0),
    )
    if fa != fb:
        return "A" if fa < fb else "B"
    ra, rb = (
        float(ca.get("quote_resolution_rate") or 0),
        float(cb.get("quote_resolution_rate") or 0),
    )
    if ra != rb:
        return "A" if ra > rb else "B"
    return "tie"


def book_effect_disagrees(memo_a: dict[str, Any], memo_b: dict[str, Any]) -> bool:
    effects = {memo_a.get("book_effect"), memo_b.get("book_effect")}
    return "blocks" in effects and len(effects) == 2


def _topup_rank(comparison_id: str, slug: str) -> str:
    return hashlib.sha256(f"{comparison_id}|{slug}|calibration".encode()).hexdigest()


CALIBRATION_RULE = (
    "Every judged pair where (a) the judge's order-consistent preference is A or B and the "
    "mechanical direction (fewer hallucination flags, then higher quote resolution rate) is "
    "the other label, or (b) one memo's verdict blocks the entry and the other's does not. "
    f"If fewer than {CALIBRATION_MIN_SAMPLE}, top up from the remaining judged pairs: those "
    "with a non-tie judge preference first, then the rest, each in ascending "
    "sha256('<comparison_id>|<slug>|calibration') order."
)


def select_calibration(
    comparison_id: str, pairs: list[dict[str, Any]], memos: dict[str, dict[str, dict[str, Any]]]
) -> list[dict[str, Any]]:
    """Owner calibration sample under ``CALIBRATION_RULE``, in manifest order of ``pairs``."""
    sample: dict[str, list[str]] = {}
    for pair in pairs:
        slug = pair["slug"]
        a, b = memos[slug]["A"], memos[slug]["B"]
        reasons = []
        direction = mechanical_direction(a, b)
        if pair["preferred"] in {"A", "B"} and direction in {"A", "B"}:
            if pair["preferred"] != direction:
                reasons.append("judge_vs_mechanical")
        if book_effect_disagrees(a, b):
            reasons.append("book_effect_disagreement")
        if reasons:
            sample[slug] = reasons
    rest = sorted(
        (p for p in pairs if p["slug"] not in sample),
        key=lambda p: (
            0 if p["preferred"] in {"A", "B"} else 1,
            _topup_rank(comparison_id, p["slug"]),
        ),
    )
    for pair in rest[: max(0, CALIBRATION_MIN_SAMPLE - len(sample))]:
        sample[pair["slug"]] = ["top_up"]
    return [
        {
            "slug": p["slug"],
            "reasons": sample[p["slug"]],
            "mechanical_direction": mechanical_direction(
                memos[p["slug"]]["A"], memos[p["slug"]]["B"]
            ),
            "book_effect_disagreement": book_effect_disagrees(
                memos[p["slug"]]["A"], memos[p["slug"]]["B"]
            ),
        }
        for p in pairs
        if p["slug"] in sample
    ]


def _initial_judge_status(manifest: dict[str, Any], moment: datetime) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "comparison_id": manifest["comparison_id"],
        "decision_rule_version": DECISION_RULE_VERSION,
        "judge_model": (manifest.get("judge") or {}).get("model", JUDGE_MODEL),
        "state": JUDGE_STATE_INCOMPLETE,
        "pairs": {},
        "spend": {"estimated_usd": 0.0, "calls": 0, "cap_usd": JUDGE_BUDGET_CAP_USD},
        "errors": [],
        "started_at": moment.isoformat(),
        "observe_only": True,
        "influences_live": False,
    }


def run_judge(
    repo_root: Path,
    *,
    now: datetime | None = None,
    api_key: str | None = None,
    runner: JudgeRunner | None = None,
    list_models: Callable[[], list[str]] | None = None,
    budget_status: Callable[[], dict[str, Any]] | None = None,
    record_spend: Callable[[float], Any] | None = None,
) -> dict[str, Any]:
    """Judge every generated pair in both orders; idempotent on rerun."""
    root = Path(repo_root)
    store = store_dir(root)
    manifest = load_json(store / "manifest.json")
    status = load_json(store / "status.json")
    moment = now or datetime.now(UTC)
    if manifest is None:
        raise FileNotFoundError(f"{store / 'manifest.json'} missing; run select first")
    judge_status = load_json(store / "judge_status.json") or _initial_judge_status(manifest, moment)
    judge_status["last_run_at"] = moment.isoformat()
    judge_status["errors"] = []
    judge_status.pop("budget_stop", None)
    judge_model = (manifest.get("judge") or {}).get("model")

    if manifest.get("decision_rule_version") != DECISION_RULE_VERSION or not judge_model:
        judge_status["errors"].append(
            f"manifest is not rule {DECISION_RULE_VERSION}; judge refuses"
        )
        return _persist(store, "judge_status.json", judge_status)
    if status is None or status.get("state") != STATE_GENERATED:
        judge_status["errors"].append("generation not finished; nothing to judge")
        return _persist(store, "judge_status.json", judge_status)
    try:
        available = (list_models or (lambda: runtime_models(api_key or "")))()
        check_judge_model(judge_model, manifest["models"], available=available)
    except Exception as exc:  # noqa: BLE001 — fail closed, no model call
        judge_status["errors"].append(f"judge model check failed: {exc}")
        return _persist(store, "judge_status.json", judge_status)
    judge_status["runtime_check"] = {
        "checked_at": moment.isoformat(),
        "judge_model": judge_model,
        "judge_family": model_family(judge_model),
        "available": True,
    }

    call = runner or default_judge_runner
    budget = budget_status or (
        lambda: weekly_ops_budget_status(estimated_memo_usd=INCUMBENT_MEMO_USD)
    )
    spend = record_spend or (
        lambda amount: record_estimated_spend(amount, pool=SPEND_POOL_WEEKLY_OPS)
    )
    as_of = str(status.get("as_of") or moment.date().isoformat())
    estimate = estimated_memo_usd(judge_model)
    budget_stop: dict[str, str] | None = None
    order = [e["slug"] for e in manifest["names"]]
    by_slug = {e["slug"]: e for e in manifest["names"]}
    generated = [s for s in order if _pair_done((status.get("pairs") or {}).get(s) or {})]

    for slug in generated:
        if budget_stop:
            break
        jp = judge_status["pairs"].setdefault(slug, {"orders": {}, "attempts": {}})
        todo = [
            o
            for o in JUDGE_ORDERS
            if not jp["orders"].get(o, {}).get("ok")
            and int(jp["attempts"].get(o) or 0) < JUDGE_MAX_ATTEMPTS
        ]
        if not todo:
            continue
        snap_dir = work_dir(root) / slug / "sources"
        expected = ((status["pairs"][slug]).get("inputs") or {}).get("sha256")
        inputs = snapshot_digest(snap_dir) if snap_dir.is_dir() else None
        if inputs is None or inputs["sha256"] != expected:
            inputs = snapshot_sources(_sources_for(by_slug[slug], root), snap_dir)
        if inputs["sha256"] != expected:
            jp["input_mismatch"] = inputs["sha256"]
            judge_status["errors"].append(
                f"{slug}: sources changed since generation; judge refuses this pair"
            )
            continue
        memos = {label: _memo(root, slug, label) for label in ("A", "B")}
        for o in todo:
            spent = float(judge_status["spend"]["estimated_usd"])
            if spent + estimate > JUDGE_BUDGET_CAP_USD:
                budget_stop = {
                    "kind": "cap",
                    "detail": f"judge cap ${JUDGE_BUDGET_CAP_USD:.2f} reached at ${spent:.2f}",
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
            shown = _order_memos(o, memos)
            prompt = judge_prompt(by_slug[slug], shown, sources_dir=snap_dir.resolve(), as_of=as_of)
            jp["attempts"][o] = int(jp["attempts"].get(o) or 0) + 1
            capture: dict[str, Any] = {}
            record: dict[str, Any] = {
                "slug": slug,
                "order": o,
                "shown_as": {"A": o[0], "B": o[1]},
                "judge_model": judge_model,
                "as_of": as_of,
                "inputs": inputs,
                "at": moment.isoformat(),
                "attempt": jp["attempts"][o],
            }
            try:
                raw = str(
                    call(
                        prompt=prompt,
                        model=judge_model,
                        api_key=api_key or "",
                        cwd=str(snap_dir.parent.resolve()),
                        as_of_date=as_of,
                        capture=capture,
                    )
                    or ""
                )
            except Exception as exc:  # noqa: BLE001 — logged; a later run may retry once
                record.update({"ok": False, "error": str(exc)[:500]})
                judge_status["errors"].append(f"{slug} {o}: {str(exc)[:200]}")
            else:
                parsed, problems = parse_judge_output(raw)
                record.update({"raw_text": raw, "parsed": parsed, "problems": problems})
                if parsed is not None and not problems:
                    record["ok"] = True
                    record["quote_check"] = check_judge_quotes(parsed, shown, sources_dir=snap_dir)
                else:
                    record["ok"] = False
                    judge_status["errors"].append(
                        f"{slug} {o}: invalid judge output ({'; '.join(problems[:3])})"
                    )
            record["prompt_sha256"] = hashlib.sha256(
                str(capture.get("prompt") or prompt).encode("utf-8")
            ).hexdigest()
            spend(estimate)
            judge_status["spend"]["estimated_usd"] = round(spent + estimate, 2)
            judge_status["spend"]["calls"] = int(judge_status["spend"]["calls"]) + 1
            jp.setdefault("cost", {})[o] = _memo_cost(capture, estimate)
            write_json(store / "judgements" / slug / f"{o}.json", record, compact=False)
            jp["orders"][o] = {"ok": bool(record.get("ok")), "at": moment.isoformat()}

    if budget_stop:
        judge_status["errors"].append(f"stopped: {budget_stop['detail']}")
        judge_status["budget_stop"] = budget_stop
    jpairs = judge_status["pairs"]

    def settled(slug: str) -> bool:
        row = jpairs.get(slug) or {}
        if row.get("input_mismatch"):
            return True
        return all(
            row.get("orders", {}).get(o, {}).get("ok")
            or int(row.get("attempts", {}).get(o) or 0) >= JUDGE_MAX_ATTEMPTS
            for o in JUDGE_ORDERS
        )

    summaries = [s for s in (summarise_pair(root, slug) for slug in generated) if s]
    judge_status["judged_pairs"] = len(summaries)
    if generated and all(settled(slug) for slug in generated) and summaries:
        memos_by_slug = {
            s["slug"]: {label: _memo(root, s["slug"], label) for label in ("A", "B")}
            for s in summaries
        }
        sample = select_calibration(manifest["comparison_id"], summaries, memos_by_slug)
        judge_results = {
            "schema_version": SCHEMA_VERSION,
            "comparison_id": manifest["comparison_id"],
            "decision_rule_version": DECISION_RULE_VERSION,
            "judge_model": judge_model,
            "generated_at": moment.isoformat(),
            "pairs": summaries,
            "order_consistent": sum(1 for s in summaries if s["order_consistent"]),
            "observe_only": True,
            "influences_live": False,
        }
        calibration = {
            "schema_version": SCHEMA_VERSION,
            "comparison_id": manifest["comparison_id"],
            "rule": CALIBRATION_RULE,
            "min_sample": CALIBRATION_MIN_SAMPLE,
            "sample": sample,
            "need_agree": calibration_need(len(sample)),
            "agree_fraction": CALIBRATION_AGREE_FRACTION,
        }
        write_json(store / "judge_results.json", judge_results, compact=False)
        write_json(store / "calibration.json", calibration, compact=False)
        slugs = [row["slug"] for row in sample]
        (store / "review.md").write_text(render_review(root, manifest, slugs), encoding="utf-8")
        write_json(
            store / "ratings_template.json", ratings_template(manifest, slugs), compact=False
        )
        if judge_status.get("state") != JUDGE_STATE_DONE:
            judge_status["ready_at"] = moment.isoformat()
        judge_status["state"] = JUDGE_STATE_DONE
    else:
        judge_status["state"] = JUDGE_STATE_INCOMPLETE
    return _persist(store, "judge_status.json", judge_status)


def _persist(store: Path, name: str, payload: dict[str, Any]) -> dict[str, Any]:
    write_json(store / name, payload, compact=False)
    return payload


# --- decision rule ---------------------------------------------------------

MIN_COMPLETE_PAIRS = 10
MIN_CHALLENGER_PREFERRED = 8
MAX_INCUMBENT_PREFERRED = 3
MIN_RUBRIC_GAIN = 1.0
WEEKLY_MEMO_HIGH = 35
STRATEGY_BOOK_MEMO_RAISE_USD = 40.0


def _side(labels: dict[str, str], pick: str | None, challenger: str) -> str:
    if pick not in {"A", "B"}:
        return "tie"
    return "challenger" if labels.get(pick) == challenger else "incumbent"


def _label_of(labels: dict[str, str], model: str) -> str:
    return next(label for label, mid in labels.items() if mid == model)


def decide(
    manifest: dict[str, Any],
    results: dict[str, Any],
    judge_results: dict[str, Any],
    calibration: dict[str, Any],
    ratings: dict[str, Any],
    key: dict[str, Any],
) -> dict[str, Any]:
    """Apply pre-declared rule v2. Reports only; nothing is switched."""
    incumbent = manifest["models"]["incumbent"]
    challenger = manifest["models"]["challenger"]
    generated = {row["slug"] for row in results.get("names") or []}
    judged = {p["slug"]: p for p in judge_results.get("pairs") or [] if p["slug"] in generated}
    sample = {row["slug"]: row for row in calibration.get("sample") or []}
    owner = ratings.get("names") or {}

    cal_rows: list[dict[str, Any]] = []
    owner_prefs = {"challenger": 0, "incumbent": 0, "tie": 0}
    owner_gains: list[float] = []
    for slug, srow in sample.items():
        orow = owner.get(slug) or {}
        opick = orow.get("preferred")
        jpick = (judged.get(slug) or {}).get("preferred")
        labels = key["names"].get(slug) or {}
        cal_rows.append(
            {
                "slug": slug,
                "reasons": srow.get("reasons"),
                "owner": opick,
                "judge": jpick,
                "agree": opick in {"A", "B", "tie"} and opick == jpick,
            }
        )
        if opick in {"A", "B", "tie"} and labels:
            owner_prefs[_side(labels, opick, challenger)] += 1
            totals = {
                model: sum(
                    int((orow.get(_label_of(labels, model)) or {}).get(k) or 0) for k in RUBRIC
                )
                for model in (incumbent, challenger)
            }
            owner_gains.append(totals[challenger] - totals[incumbent])
    agree = sum(1 for row in cal_rows if row["agree"])
    rated = sum(1 for row in cal_rows if row["owner"] in {"A", "B", "tie"})
    need = calibration_need(len(sample))
    judge_trusted = bool(
        len(sample) >= CALIBRATION_MIN_SAMPLE and rated == len(sample) and agree >= need
    )

    prefs = {"challenger": 0, "incumbent": 0, "tie": 0}
    effect = {"challenger": 0, "incumbent": 0, "tie": 0}
    gains: list[float] = []
    governed_by_owner: list[str] = []
    for slug, pair in judged.items():
        labels = key["names"][slug]
        pick = pair["preferred"]
        srow = sample.get(slug) or {}
        opick = (owner.get(slug) or {}).get("preferred")
        if srow.get("book_effect_disagreement") and opick in {"A", "B"}:
            pick = opick
            governed_by_owner.append(slug)
        side = _side(labels, pick, challenger)
        prefs[side] += 1
        if srow.get("book_effect_disagreement"):
            effect[side] += 1
        scores = pair["scores"]
        gains.append(
            float(scores[_label_of(labels, challenger)]["total"])
            - float(scores[_label_of(labels, incumbent)]["total"])
        )

    agg = results.get("by_model") or {}
    inc, chal = agg.get(incumbent) or {}, agg.get(challenger) or {}
    per_memo = chal.get("charged_usd_per_memo") or estimated_memo_usd(challenger)
    weekly = round(per_memo * WEEKLY_MEMO_HIGH, 2)
    complete = len(judged)
    checks = {
        "complete_pairs": {
            "value": complete,
            "need": f">= {MIN_COMPLETE_PAIRS} pairs with both memos and both judge orders",
            "ok": complete >= MIN_COMPLETE_PAIRS,
        },
        "judge_prefers_challenger": {
            "value": prefs,
            "need": (
                f"order-consistent judge preference: challenger >= {MIN_CHALLENGER_PREFERRED} "
                f"and incumbent <= {MAX_INCUMBENT_PREFERRED} (owner's non-tie pick governs "
                "book-effect disagreements)"
            ),
            "ok": prefs["challenger"] >= MIN_CHALLENGER_PREFERRED
            and prefs["incumbent"] <= MAX_INCUMBENT_PREFERRED,
        },
        "judge_rubric_gain": {
            "value": round(mean(gains), 2) if gains else None,
            "need": f"mean judge challenger minus incumbent total (of 15) >= {MIN_RUBRIC_GAIN}",
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
            "value": effect,
            "need": "where one verdict blocks entry and the other does not, challenger preferred at least as often",
            "ok": effect["challenger"] >= effect["incumbent"],
        },
        "weekly_cost_fits": {
            "value": {"per_memo_usd": per_memo, "weekly_high_usd": weekly},
            "need": f"{WEEKLY_MEMO_HIGH} memos a week <= ${STRATEGY_BOOK_MEMO_RAISE_USD:.0f} strategy_book_memo_raise",
            "ok": weekly <= STRATEGY_BOOK_MEMO_RAISE_USD,
        },
        "judge_calibration": {
            "value": {"sample": len(sample), "rated": rated, "agree": agree},
            "need": (
                f"owner agrees with the judge's preference on >= {need} of {len(sample)} "
                f"(ceil({CALIBRATION_AGREE_FRACTION} x sample)), sample >= {CALIBRATION_MIN_SAMPLE}"
            ),
            "ok": judge_trusted,
        },
    }
    mechanical_ok = all(
        checks[name]["ok"]
        for name in (
            "complete_pairs",
            "citations_not_worse",
            "hallucination_not_worse",
            "weekly_cost_fits",
            "book_effect_disagreements",
        )
    )
    owner_gain = round(mean(owner_gains), 2) if owner_gains else None
    overwhelming = bool(
        owner_prefs["incumbent"] == 0
        and owner_prefs["challenger"] >= need
        and owner_gain is not None
        and owner_gain >= MIN_RUBRIC_GAIN
    )
    if judge_trusted:
        governing = "judge"
        if all(row["ok"] for row in checks.values()):
            outcome = "switch"
        elif complete >= MIN_COMPLETE_PAIRS and (
            prefs["incumbent"] >= prefs["challenger"] or not checks["hallucination_not_worse"]["ok"]
        ):
            outcome = "keep"
        else:
            outcome = "inconclusive_keep"
    else:
        governing = "owner_sample"
        if overwhelming and mechanical_ok:
            outcome = "switch"
        elif complete >= MIN_COMPLETE_PAIRS and (
            owner_prefs["incumbent"] >= owner_prefs["challenger"]
            or not checks["hallucination_not_worse"]["ok"]
        ):
            outcome = "keep"
        else:
            outcome = "inconclusive_keep"
    return {
        "comparison_id": manifest["comparison_id"],
        "decision_rule_version": DECISION_RULE_VERSION,
        "outcome": outcome,
        "governing": governing,
        "judge_trusted": judge_trusted,
        "judge_model": judge_results.get("judge_model"),
        "checks": checks,
        "calibration": {
            "sample": len(sample),
            "rated": rated,
            "agree": agree,
            "need": need,
            "rows": cal_rows,
            "owner_governed_book_effect": governed_by_owner,
        },
        "owner_sample": {
            "preferences": owner_prefs,
            "mean_rubric_gain": owner_gain,
            "overwhelming_challenger": overwhelming,
        },
        "incumbent": incumbent,
        "challenger": challenger,
        "note": (
            "switch: owner approves, then the memo model change is logged as an "
            "operational_switches row on docs/data/strategy_book_registration.json "
            "(not a rule change) and the memo runner's model is changed in its own PR. "
            "keep / inconclusive_keep: composer-2.5 stays; nothing changes. judge_trusted "
            "records whether this judge passed owner calibration for reuse in later comparisons."
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


def decide_from_store(store: Path) -> dict[str, Any]:
    """``decide`` on the committed store files; raises if any input is missing."""
    names = ("manifest", "results", "judge_results", "calibration", "ratings", "blind_key")
    loaded = {name: load_json(store / f"{name}.json") for name in names}
    missing = [f"{name}.json" for name, payload in loaded.items() if not payload]
    if missing:
        raise FileNotFoundError(f"need {', '.join(missing)}")
    return decide(
        loaded["manifest"],
        loaded["results"],
        loaded["judge_results"],
        loaded["calibration"],
        loaded["ratings"],
        loaded["blind_key"],
    )


def _age_days(raw: Any, moment: datetime) -> int:
    try:
        when = datetime.fromisoformat(str(raw or "").replace("Z", "+00:00"))
    except ValueError:
        return 0
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return (moment - when).days


def findings(repo_root: Path, now: datetime | None = None) -> list[dict[str, Any]]:
    """Read-only lifecycle findings. Never auto-fixable; no rememo or ingest.

    Stages: awaiting generation, awaiting judge, ready for owner calibration, stale, decided.
    """
    moment = now or datetime.now(UTC)
    store = store_dir(Path(repo_root))
    manifest = load_json(store / "manifest.json")
    if manifest is None:
        return [_finding("warn", TITLE_FAILED, f"{STORE_REL}/manifest.json missing or unreadable.")]
    if manifest.get("decision_rule_version") != DECISION_RULE_VERSION:
        return [
            _finding(
                "warn",
                TITLE_FAILED,
                f"manifest is not rule {DECISION_RULE_VERSION} (judge amendment); generation "
                "and judge refuse until it is recorded.",
            )
        ]
    status = load_json(store / "status.json")
    names = len(manifest.get("names") or [])
    budget = manifest.get("budget") or {}
    dispatch = "gh workflow run memo-model-comparison.yml -f action=generate"
    if status is None:
        return [
            _finding(
                "info",
                TITLE_AWAITING,
                f"{names} names selected (selection {RULE_VERSION}, decision rule "
                f"{DECISION_RULE_VERSION}); estimated ${budget.get('comparison_estimated_total_usd')} "
                f"of a ${budget.get('comparison_cap_usd')} cap (memos and judge). Runs on the next "
                f"scheduled slot or `{dispatch}`.",
            )
        ]
    out: list[dict[str, Any]] = []
    if status.get("errors"):
        out.append(
            _finding(
                "warn",
                TITLE_FAILED,
                f"Generation {status.get('state')}; {status.get('complete_pairs', 0)}/{names} pairs. "
                + "; ".join(str(e) for e in status["errors"][:4]),
            )
        )
    if status.get("state") != STATE_GENERATED:
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
    judge = load_json(store / "judge_status.json")
    if judge and judge.get("errors"):
        out.append(
            _finding(
                "warn",
                TITLE_FAILED,
                f"Judge {judge.get('state')}; {judge.get('judged_pairs', 0)} pairs judged. "
                + "; ".join(str(e) for e in judge["errors"][:4]),
            )
        )
    if judge is None or judge.get("state") != JUDGE_STATE_DONE:
        if not out:
            out.append(
                _finding(
                    "info",
                    TITLE_AWAITING_JUDGE,
                    f"{status.get('complete_pairs', 0)}/{names} pairs generated; judge "
                    f"{(manifest.get('judge') or {}).get('model')} has judged "
                    f"{(judge or {}).get('judged_pairs', 0)} in both orders. "
                    "`gh workflow run memo-model-comparison.yml -f action=judge`.",
                )
            )
        return out
    ratings = load_json(store / "ratings.json")
    done, total = ratings_progress(ratings or load_json(store / "ratings_template.json"))
    if ratings and total and done == total:
        verdict = decide_from_store(store)
        failed = [name for name, row in verdict["checks"].items() if not row["ok"]]
        out.append(
            _finding(
                "info",
                TITLE_DECIDED,
                f"Outcome {verdict['outcome']} ({verdict['incumbent']} vs {verdict['challenger']}); "
                f"judge_trusted {str(verdict['judge_trusted']).lower()}, governed by "
                f"{verdict['governing']}; failed checks: {', '.join(failed) or 'none'}. A switch "
                "needs owner approval and an operational_switches row on the registration. "
                "Observe-only.",
            )
        )
        return out
    age = _age_days(judge.get("ready_at"), moment)
    severity, title = ("warn", TITLE_STALE) if age > REVIEW_STALE_DAYS else ("info", TITLE_READY)
    out.append(
        _finding(
            severity,
            title,
            f"{done}/{total} calibration names rated; ready {age} days. Read {STORE_REL}/review.md, "
            "copy ratings_template.json to ratings.json and fill it (human task "
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
    if status.get("state") == STATE_GENERATED:
        return False
    stop = status.get("budget_stop") or {}
    return stop.get("kind") != "cap"


def due_for_judge(repo_root: Path) -> bool:
    """True once generation is done while some judge order has attempts left and no cap stop."""
    store = store_dir(Path(repo_root))
    status = load_json(store / "status.json")
    if status is None or status.get("state") != STATE_GENERATED:
        return False
    judge = load_json(store / "judge_status.json")
    if judge is None:
        return True
    if judge.get("state") == JUDGE_STATE_DONE:
        return False
    return (judge.get("budget_stop") or {}).get("kind") != "cap"


__all__ = [
    "BUDGET_CAP_USD",
    "CALIBRATION_RULE",
    "CHALLENGER_MODEL",
    "COMPARISON_APPENDIX",
    "DECISION_RULE_VERSION",
    "INCUMBENT_MODEL",
    "JUDGE_BUDGET_CAP_USD",
    "JUDGE_MODEL",
    "SELECTION_RULE",
    "TITLE_AWAITING",
    "TITLE_AWAITING_JUDGE",
    "TITLE_DECIDED",
    "TITLE_FAILED",
    "TITLE_READY",
    "TITLE_STALE",
    "amend_rule_v2",
    "book_effect",
    "check_judge_model",
    "decide",
    "decide_from_store",
    "due_for_generation",
    "due_for_judge",
    "findings",
    "run_generation",
    "run_judge",
    "score_memo",
    "select_calibration",
    "select_names",
    "strongest_configured_grok",
]
