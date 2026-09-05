"""Observe-only material-event journal from existing news manifests.

Classifies buy∪boundary headlines into leadership / M&A / contract / strategy
events, joins later filings and archive forward returns, and scores rule
confirmation. Does not fetch article HTML, crawl IR sites, or write screen
weights. Calendar span is the point: start the journal now so later filings
and returns can prove whether the extractor found the right facts.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.backtest import load_run_snapshots
from value_investor.news_phrase_trajectory import (
    _forward_returns_from_archive,
    _parse_dt,
    _snapshot_index,
    load_news_manifest,
    select_buy_boundary_cohort,
)
from value_investor.research.filings import headline_relevant_to_issuer
from value_investor.storage import read_json, resolve_json_path, write_json

SCHEMA_VERSION = 1
JOURNAL_FILENAME = "news_event_journal.json"
RULES_FILENAME = "news_event_rules.json"
STATE_FILENAME = "news_event_journal_state.json"
REVIEW_MD_FILENAME = "news_event_journal_review.md"

SOURCE_POOL = "buy_boundary"
EXTRACTOR_VERSION = "headline-rules-v1.1"
RICHER_SOURCE = "guardian_open_platform"
FILING_LOOKAHEAD_DAYS = 400
BODY_SCAN_CHARS = 24_000
MIN_CONFIRM_N = 4
PROMISING_CONFIRM_RATE = 0.4

EVENT_TYPES = ("leadership", "m_and_a", "contract", "strategy")

_CURRENCY_NOISE = re.compile(
    r"\b(dirham|dollar|euro|sterling|yen|yuan|pound|fx|forex|currency|versus|vs)\b",
    flags=re.I,
)
_ISSUER_LEGAL = frozenset(
    "plc ltd limited nv sa se ag spa gmbh group company companies holdings holdco".split()
)
_CLICKBAIT = re.compile(
    r"time to buy|should you buy|buy,\s*hold or exit|warrant your attention|"
    r"makes an interesting case|interesting case",
    flags=re.I,
)
_M_AND_A_NOT_DEAL = re.compile(
    r"\b(buyback|share repurchase|repurchase[sd]?|treasury shares?|"
    r"incentive plan|employee stock|depositary shares)\b|"
    r"\bacquires? \d[\d,]*\s+shares?\b|"
    r"\bacquires? shares\b|"
    r"\b(director|insider|insiders|non-executive|executive|cfo)\b.{0,40}\bacqui",
    flags=re.I,
)
_GENERIC_CONFIRM = frozenset(
    """
    earnings revenue profit growth shares share stock stocks group plc ltd
    limited case attention warrant interesting time hold exit buy company
    companies holdings holdco update report results
    """.split()
)
_CONTENT_STOPS = frozenset(
    """
    a an the and or but if in on at to for of from with by as is are was were be
    been being it its this that these those not no nor so than then too very can
    could should would will just about into over after before under again further
    once here there when where why how all any both each few more most other some
    such only own same says say said week month year today yesterday update
    updates trading report reports results shares share stock stocks market
    markets london ftse uk british announced announce announces announcement
    """.split()
)

# Tight phrases: role+action for leadership; avoid lone "bid" / "chair" / "approach".
_TYPE_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "leadership": (
        re.compile(
            r"\b(ceo|cfo|chairman|chairwoman|chief executive|chief financial officer)\b"
            r".{0,40}\b(resign|resigns|resigned|steps? down|appoint|appointed|appoints|"
            r"named|names|succeeds|succession)\b",
            flags=re.I,
        ),
        re.compile(
            r"\b(resign|resigns|resigned|steps? down|appoint|appointed|appoints|"
            r"named|names|succeeds|succession)\b.{0,40}"
            r"\b(ceo|cfo|chairman|chairwoman|chief executive|chief financial officer)\b",
            flags=re.I,
        ),
        re.compile(r"\b(new|interim)\s+(ceo|cfo|chairman|chairwoman)\b", flags=re.I),
        re.compile(r"\b(ceo|cfo)\s+(succession|departure|exit)\b", flags=re.I),
    ),
    "m_and_a": (
        re.compile(r"\b(acqui(?:re|res|red|sition|ring)|takeover|merger)\b", flags=re.I),
        re.compile(r"\bagrees? to (buy|acquire)\b", flags=re.I),
        re.compile(r"\b(recommended|possible|potential)\s+(offer|bid)\b", flags=re.I),
        re.compile(r"\b(disposal|divest(?:s|ed|iture|ment)?)\b", flags=re.I),
    ),
    "contract": (
        re.compile(r"\b(contract|tender)\s+(win|won|wins|award|awarded|loss|lost)\b", flags=re.I),
        re.compile(r"\b(win|won|wins|award|awarded|loss|lost|loses)\s+(a\s+)?(contract|tender)\b", flags=re.I),
        re.compile(r"\b(major|key|new)\s+contract\b", flags=re.I),
        re.compile(r"\b(lost|loses|wins|won)\s+(a\s+)?(customer|client)\b", flags=re.I),
    ),
    "strategy": (
        re.compile(r"\bstrategic review\b", flags=re.I),
        re.compile(r"\bstrateg(?:y|ic)\s+(shift|pivot|reset|u-?turn|overhaul)\b", flags=re.I),
        re.compile(r"\b(new|updated)\s+strategy\b", flags=re.I),
        re.compile(r"\b(exit|exits|exiting)\s+(the\s+)?(market|division|business)\b", flags=re.I),
    ),
}

# Fields that must be present after title+teaser+confirming filing, else
# the learning loop flags a richer-source seek (Guardian later; not fetched here).
REQUIRED_FACTS: dict[str, tuple[str, ...]] = {
    "leadership": (),
    "m_and_a": ("size", "likelihood"),
    "contract": ("size",),
    "strategy": ("likelihood",),
}

_SIZE_RE = re.compile(
    r"£\s?[\d.,]+\s?(?:bn|billion|m|million)?|"
    r"\$\s?[\d.,]+\s?(?:bn|billion|m|million)?|"
    r"\b[\d.,]+\s?(?:bn|billion|million)\b",
    flags=re.I,
)
_LIKELIHOOD_RE = re.compile(
    r"\b(talks?|approach(?:ed|es)?|possible|potential|rumour(?:ed)?|rumored|"
    r"recommended|agrees?|agreed|confirms?|confirmed|completed?|completes|"
    r"wins?|won|awarded|lost|resigns?|resigned|appoints?|appointed|named)\b",
    flags=re.I,
)
_TIMELINE_RE = re.compile(
    r"\b(h1|h2|q[1-4]|fy\s?\d{2,4}|20\d{2}|next year|this year|"
    r"deadline|completion|expected to close|within \d+|"
    r"by (?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*)\b",
    flags=re.I,
)

_TYPE_CONFIRM_TERMS: dict[str, tuple[str, ...]] = {
    "leadership": (
        "ceo",
        "cfo",
        "chairman",
        "chairwoman",
        "chief executive",
        "resign",
        "appointed",
        "succession",
        "steps down",
    ),
    "m_and_a": (
        "acquisition",
        "acquire",
        "acquired",
        "takeover",
        "merger",
        "disposal",
        "divest",
        "offer",
    ),
    "contract": ("contract", "tender", "customer", "client"),
    "strategy": (
        "strategic review",
        "strategy",
        "pivot",
        "reset",
        "u-turn",
        "overhaul",
    ),
}


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def _issuer_name_tokens(name: str | None) -> list[str]:
    tokens = [
        tok
        for tok in re.split(r"[^a-z0-9]+", (name or "").lower())
        if len(tok) >= 4 and tok not in _ISSUER_LEGAL
    ]
    return tokens[:6]


def issuer_mentioned(
    title: str,
    summary: str,
    *,
    company_name: str | None,
    ticker: str,
) -> bool:
    """Require a real issuer hit; reject short-EPIC currency/FX homonyms."""
    text = f"{title} {summary}".strip()
    if not text or not headline_relevant_to_issuer(text, company_name or "", ticker):
        return False
    epic = ticker.split(".")[0]
    if len(epic) <= 3 and _CURRENCY_NOISE.search(text):
        lower = text.lower()
        return any(tok in lower for tok in _issuer_name_tokens(company_name))
    return True


def classify_headline(title: str, summary: str = "") -> dict[str, Any]:
    """Return matched event types and the patterns that fired. No issuer gate.

    Classify the title only. RSS teasers are full of ``time to buy`` clickbait
    that would poison the journal if mixed in.
    """
    del summary  # kept for call-site compatibility; do not classify teasers
    text = (title or "").strip()
    matched: list[str] = []
    rules: list[str] = []
    for event_type, patterns in _TYPE_PATTERNS.items():
        if event_type == "m_and_a" and (
            _CLICKBAIT.search(text) or _M_AND_A_NOT_DEAL.search(text)
        ):
            continue
        for index, pattern in enumerate(patterns):
            if pattern.search(text):
                matched.append(event_type)
                rules.append(f"{event_type}:{index}")
                break
    return {
        "event_types": matched,
        "primary_event_type": matched[0] if matched else None,
        "matched_rules": rules,
        "claim": text[:220] or None,
    }


def _fact_hit(pattern: re.Pattern[str], text: str) -> dict[str, Any]:
    match = pattern.search(text or "")
    snippet = match.group(0).strip() if match else None
    return {"found": bool(snippet), "snippet": snippet}


def extract_event_facts(*texts: str) -> dict[str, dict[str, Any]]:
    """Pull size / likelihood / timeline tokens from already-held text."""
    blob = " ".join(part for part in texts if part)
    return {
        "size": _fact_hit(_SIZE_RE, blob),
        "likelihood": _fact_hit(_LIKELIHOOD_RE, blob),
        "timeline": _fact_hit(_TIMELINE_RE, blob),
    }


def assess_evidence(
    event_type: str,
    title: str,
    summary: str = "",
    filing_text: str = "",
) -> dict[str, Any]:
    """Flag missing required facts as a richer-source trigger. Does not fetch."""
    facts = extract_event_facts(title, summary, filing_text)
    required = REQUIRED_FACTS.get(event_type) or ()
    missing = [name for name in required if not facts[name]["found"]]
    seek = bool(missing)
    return {
        "facts": facts,
        "required_fields": list(required),
        "missing_fields": missing,
        "evidence_status": "insufficient" if seek else "sufficient",
        "seek_richer_source": seek,
        "richer_source": RICHER_SOURCE if seek else None,
    }


def event_id(ticker: str, published_at: datetime, title: str) -> str:
    stamp = published_at.date().isoformat()
    norm = re.sub(r"\s+", " ", (title or "").strip().lower())
    digest = hashlib.sha1(f"{ticker}|{stamp}|{norm}".encode()).hexdigest()
    return digest[:16]


def _content_tokens(title: str, *, company_name: str | None, ticker: str) -> list[str]:
    stops = set(_CONTENT_STOPS) | set(_issuer_name_tokens(company_name))
    epic = ticker.split(".")[0].lower()
    if epic:
        stops.add(epic)
    tokens: list[str] = []
    seen: set[str] = set()
    for tok in re.findall(r"[a-z0-9][a-z0-9'-]{3,}", (title or "").lower()):
        if tok in stops or tok in _GENERIC_CONFIRM or tok.isdigit() or tok in seen:
            continue
        seen.add(tok)
        tokens.append(tok)
        if len(tokens) >= 6:
            break
    return tokens


@dataclass(frozen=True)
class FilingRow:
    filing_id: str
    published_at: datetime
    headline: str
    has_body: bool
    body_text: str


def load_filings_for_join(data_dir: Path, ticker: str) -> list[FilingRow]:
    index_path = resolve_json_path(
        data_dir / "research" / ticker / "sources" / "filings" / "filings_index.json"
    )
    if index_path is None:
        return []
    try:
        payload = read_json(index_path)
    except (OSError, ValueError, TypeError):
        return []
    bodies_dir = index_path.parent / "bodies"
    rows: list[FilingRow] = []
    for item in payload.get("filings") or []:
        if not isinstance(item, dict):
            continue
        published = _parse_dt(str(item.get("published_at") or ""))
        if published is None:
            continue
        body_text = ""
        if item.get("has_body"):
            body_path = item.get("body_path")
            path = Path(str(body_path)) if body_path else bodies_dir / f"{item.get('id')}.txt"
            if not path.is_file():
                path = bodies_dir / f"{item.get('id')}.txt"
            if path.is_file():
                try:
                    body_text = path.read_text(encoding="utf-8", errors="replace")[:BODY_SCAN_CHARS]
                except OSError:
                    body_text = ""
        rows.append(
            FilingRow(
                filing_id=str(item.get("id") or ""),
                published_at=published,
                headline=str(item.get("headline") or item.get("title") or ""),
                has_body=bool(item.get("has_body") and body_text),
                body_text=body_text,
            )
        )
    rows.sort(key=lambda row: row.published_at)
    return rows


def _text_has_any(text: str, terms: tuple[str, ...]) -> bool:
    lower = (text or "").lower()
    return any(term in lower for term in terms)


def join_later_filing(
    *,
    published_at: datetime,
    event_type: str,
    title: str,
    company_name: str | None,
    ticker: str,
    filings: list[FilingRow],
    lookahead_days: int = FILING_LOOKAHEAD_DAYS,
) -> dict[str, Any]:
    """Find the earliest later filing that mentions this event class."""
    empty = {
        "later_filing_available": False,
        "later_filing_id": None,
        "later_filing_published_at": None,
        "days_to_later_filing": None,
        "confirmation_kind": None,
        "filing_evidence_text": "",
    }
    window_end = published_at + timedelta(days=lookahead_days)
    later = [row for row in filings if published_at <= row.published_at <= window_end]
    if not later:
        return empty
    terms = _TYPE_CONFIRM_TERMS.get(event_type) or ()
    tokens = _content_tokens(title, company_name=company_name, ticker=ticker)
    empty["later_filing_available"] = True

    def _confirm(row: FilingRow, kind: str) -> dict[str, Any]:
        delta = (row.published_at.date() - published_at.date()).days
        evidence = " ".join(part for part in (row.headline, row.body_text) if part)
        return {
            "later_filing_available": True,
            "later_filing_id": row.filing_id or None,
            "later_filing_published_at": _iso(row.published_at),
            "days_to_later_filing": delta,
            "confirmation_kind": kind,
            "filing_evidence_text": evidence[:BODY_SCAN_CHARS],
        }

    for row in later:
        if _text_has_any(row.headline, terms):
            return _confirm(row, "headline_match")
    if tokens:
        for row in later:
            if not row.body_text:
                continue
            body_l = row.body_text.lower()
            if _text_has_any(body_l, terms) and any(tok in body_l for tok in tokens):
                return _confirm(row, "body_match")
    return empty


def _load_previous_journal(data_dir: Path) -> dict[str, dict[str, Any]]:
    path = resolve_json_path(data_dir / JOURNAL_FILENAME)
    if path is None:
        return {}
    payload = read_json(path)
    events = payload.get("events") if isinstance(payload, dict) else None
    if not isinstance(events, list):
        return {}
    by_id: dict[str, dict[str, Any]] = {}
    for row in events:
        if isinstance(row, dict) and row.get("event_id"):
            by_id[str(row["event_id"])] = row
    return by_id


def _load_watermarks(data_dir: Path) -> dict[str, datetime]:
    path = resolve_json_path(data_dir / STATE_FILENAME)
    if path is None:
        return {}
    payload = read_json(path)
    out: dict[str, datetime] = {}
    for ticker, stamp in (payload.get("ticker_watermarks") or {}).items():
        parsed = _parse_dt(str(stamp))
        if parsed is not None:
            out[str(ticker)] = parsed
    return out


def _score_rules(events: list[dict[str, Any]]) -> dict[str, Any]:
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        by_type[str(event.get("primary_event_type") or "")].append(event)

    rows: list[dict[str, Any]] = []
    for event_type in EVENT_TYPES:
        bucket = by_type.get(event_type) or []
        with_later = [row for row in bucket if row.get("later_filing_available")]
        confirmed = [row for row in with_later if row.get("confirmation_kind")]
        labeled = [
            float(row["forward_return_4w"])
            for row in bucket
            if row.get("forward_return_4w") is not None
        ]
        gaps = [row for row in bucket if row.get("seek_richer_source")]
        confirm_rate = (
            round(len(confirmed) / len(with_later), 4) if with_later else None
        )
        gap_rate = round(len(gaps) / len(bucket), 4) if bucket else None
        if confirm_rate is None or len(with_later) < MIN_CONFIRM_N:
            status = "watch"
            reason = "insufficient_later_filings"
        elif confirm_rate >= PROMISING_CONFIRM_RATE:
            status = "promising"
            reason = "confirmation_rate_cleared"
        else:
            status = "weak"
            reason = "low_confirmation_rate"
        rows.append(
            {
                "event_type": event_type,
                "event_count": len(bucket),
                "later_filing_count": len(with_later),
                "confirmed_count": len(confirmed),
                "confirmation_rate": confirm_rate,
                "labeled_4w_count": len(labeled),
                "mean_forward_return_4w": (
                    round(sum(labeled) / len(labeled), 6) if labeled else None
                ),
                "seek_richer_source_count": len(gaps),
                "evidence_gap_rate": gap_rate,
                "status": status,
                "status_reason": reason,
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "scope": "news_event_rules",
        "observe_only": True,
        "extractor_version": EXTRACTOR_VERSION,
        "min_confirm_n": MIN_CONFIRM_N,
        "promising_confirm_rate": PROMISING_CONFIRM_RATE,
        "event_types": rows,
    }


def _format_review_markdown(journal: dict[str, Any], rules: dict[str, Any]) -> str:
    lines = [
        "# News event journal (observe-only)",
        "",
        f"- Generated: `{journal.get('generated_at')}`",
        f"- Source pool: `{journal.get('source_pool')}`",
        f"- Mode: `{journal.get('mode')}`",
        f"- Extractor: `{journal.get('extractor_version')}`",
        f"- Cohort tickers: **{journal.get('cohort_ticker_count')}** "
        f"(with news: **{journal.get('tickers_with_news')}**)",
        f"- Articles walked: **{journal.get('article_count')}**",
        f"- Issuer rejects: **{journal.get('issuer_reject_count')}**",
        f"- Events kept: **{journal.get('event_count')}**",
        f"- Later filings available: **{journal.get('later_filing_available_count')}**",
        f"- Filing-confirmed: **{journal.get('confirmed_count')}**",
        f"- Seek richer source (insufficient facts): "
        f"**{journal.get('seek_richer_source_count')}**",
        "",
        "## Rule confirmation (later filings, not live scores)",
        "",
        "| type | events | later filings | confirmed | rate | seek richer | status |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in rules.get("event_types") or []:
        rate = row.get("confirmation_rate")
        rate_s = "—" if rate is None else f"{rate:.0%}"
        lines.append(
            f"| `{row.get('event_type')}` | {row.get('event_count')} | "
            f"{row.get('later_filing_count')} | {row.get('confirmed_count')} | "
            f"{rate_s} | {row.get('seek_richer_source_count')} | "
            f"{row.get('status')} |"
        )
    lines.extend(["", "## Recent events", ""])
    recent = list(journal.get("events") or [])[-12:]
    if not recent:
        lines.append("_No issuer-filtered material events this run._")
    else:
        lines.append("| date | ticker | type | confirm | evidence | claim |")
        lines.append("|---|---|---|---|---|---|")
        for row in recent:
            stamp = str(row.get("published_at") or "")[:10]
            kind = row.get("confirmation_kind") or (
                "pending" if not row.get("later_filing_available") else "unconfirmed"
            )
            evidence = "seek" if row.get("seek_richer_source") else (row.get("evidence_status") or "")
            claim = str(row.get("claim") or "").replace("|", "/")
            lines.append(
                f"| {stamp} | `{row.get('ticker')}` | `{row.get('primary_event_type')}` | "
                f"{kind} | {evidence} | {claim} |"
            )
    gaps = [row for row in (journal.get("events") or []) if row.get("seek_richer_source")][-8:]
    lines.extend(["", "## Insufficient evidence (seek richer source later)", ""])
    if not gaps:
        lines.append("_No events flagged for a richer source this run._")
    else:
        lines.append("| date | ticker | type | missing | claim |")
        lines.append("|---|---|---|---|---|")
        for row in gaps:
            stamp = str(row.get("published_at") or "")[:10]
            missing = ", ".join(row.get("missing_fields") or []) or "—"
            claim = str(row.get("claim") or "").replace("|", "/")
            lines.append(
                f"| {stamp} | `{row.get('ticker')}` | `{row.get('primary_event_type')}` | "
                f"{missing} | {claim} |"
            )
    lines.extend(["", "## Coverage notes", ""])
    for note in journal.get("notes") or []:
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)


def extract_events_for_ticker(
    *,
    ticker: str,
    name: str | None,
    articles: list[dict[str, Any]],
    filings: list[FilingRow],
    indexed_snapshots: list[Any],
    since: datetime | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    counts = {
        "articles": 0,
        "issuer_reject": 0,
        "no_event": 0,
        "events": 0,
    }
    events: list[dict[str, Any]] = []
    for article in sorted(articles, key=lambda row: str(row.get("published_at") or "")):
        published_at = _parse_dt(str(article.get("published_at") or ""))
        if published_at is None:
            continue
        if since is not None and published_at <= since:
            continue
        counts["articles"] += 1
        title = str(article.get("title") or "")
        summary = str(article.get("summary") or article.get("teaser") or "")
        if not issuer_mentioned(title, summary, company_name=name, ticker=ticker):
            counts["issuer_reject"] += 1
            continue
        classified = classify_headline(title, summary)
        if not classified["primary_event_type"]:
            counts["no_event"] += 1
            continue
        forwards = _forward_returns_from_archive(ticker, published_at, indexed_snapshots)
        join = join_later_filing(
            published_at=published_at,
            event_type=classified["primary_event_type"],
            title=title,
            company_name=name,
            ticker=ticker,
            filings=filings,
        )
        filing_text = str(join.pop("filing_evidence_text", "") or "")
        evidence = assess_evidence(
            classified["primary_event_type"],
            title,
            summary,
            filing_text,
        )
        counts["events"] += 1
        events.append(
            {
                "event_id": event_id(ticker, published_at, title),
                "ticker": ticker,
                "name": name,
                "published_at": _iso(published_at),
                "source": article.get("source"),
                "article_id": article.get("id"),
                "url": article.get("url"),
                "title": title,
                "claim": classified["claim"],
                "primary_event_type": classified["primary_event_type"],
                "event_types": classified["event_types"],
                "matched_rules": classified["matched_rules"],
                "issuer_match": True,
                "extractor_version": EXTRACTOR_VERSION,
                "forward_return_4w": forwards.get("forward_return_4w"),
                "forward_return_8w": forwards.get("forward_return_8w"),
                "forward_return_12w": forwards.get("forward_return_12w"),
                **join,
                **evidence,
            }
        )
    return events, counts


def run_news_event_journal(
    data_dir: Path,
    *,
    mode: str = "full",
    tickers: list[str] | None = None,
) -> dict[str, Any]:
    """Walk buy∪boundary news manifests and write observe-only journal artifacts."""
    if mode not in {"full", "rolling"}:
        raise ValueError(f"unsupported mode: {mode}")
    data_dir = Path(data_dir)
    cohort = select_buy_boundary_cohort(data_dir)
    if tickers:
        wanted = {item.strip() for item in tickers if item.strip()}
        cohort = [row for row in cohort if row["ticker"] in wanted]
    snapshots = load_run_snapshots(data_dir / "history")
    indexed = _snapshot_index(snapshots)
    previous = {} if mode == "full" else _load_previous_journal(data_dir)
    watermarks = {} if mode == "full" else _load_watermarks(data_dir)

    events_by_id = dict(previous)
    new_watermarks: dict[str, str] = {
        ticker: stamp.isoformat() for ticker, stamp in watermarks.items()
    }
    per_ticker: list[dict[str, Any]] = []
    articles_total = 0
    issuer_rejects = 0
    tickers_with_news = 0

    for member in cohort:
        ticker = member["ticker"]
        articles = load_news_manifest(data_dir, ticker)
        if articles:
            tickers_with_news += 1
        filings = load_filings_for_join(data_dir, ticker)
        since = watermarks.get(ticker) if mode == "rolling" else None
        extracted, counts = extract_events_for_ticker(
            ticker=ticker,
            name=member.get("name"),
            articles=articles,
            filings=filings,
            indexed_snapshots=indexed,
            since=since,
        )
        dated_ok = [
            dt
            for dt in (_parse_dt(str(row.get("published_at") or "")) for row in articles)
            if dt is not None
        ]
        if mode == "rolling":
            articles_total += counts["articles"]
        else:
            articles_total += len(dated_ok)
        issuer_rejects += counts["issuer_reject"]
        for event in extracted:
            events_by_id[event["event_id"]] = event
        latest_article_at = max(dated_ok) if dated_ok else None
        if latest_article_at is not None:
            new_watermarks[ticker] = latest_article_at.isoformat()
        ticker_event_count = sum(
            1 for row in events_by_id.values() if row.get("ticker") == ticker
        )
        per_ticker.append(
            {
                "ticker": ticker,
                "name": member.get("name"),
                "cohort_tags": member.get("cohort_tags"),
                "article_count": len(articles),
                "event_count": ticker_event_count,
                "new_event_count": len(extracted),
                "issuer_reject_count": counts["issuer_reject"],
                "latest_article_at": _iso(latest_article_at),
            }
        )

    events = sorted(
        events_by_id.values(),
        key=lambda row: (str(row.get("published_at") or ""), str(row.get("ticker") or "")),
    )
    rules = _score_rules(events)
    generated_at = datetime.now(UTC).isoformat()
    confirmed = sum(1 for row in events if row.get("confirmation_kind"))
    later_avail = sum(1 for row in events if row.get("later_filing_available"))
    seek_richer = sum(1 for row in events if row.get("seek_richer_source"))
    notes = [
        "Observe-only: does not modify screen weights, paper knobs, or AI-judgment prompts.",
        "Input is existing news_manifest title+teaser — no article HTML and no IR crawl.",
        "Issuer gate reuses headline_relevant_to_issuer plus a short-EPIC currency reject.",
        "Filing confirmation looks at later filings_index headlines/bodies already on disk.",
        "Forward returns use archive snapshots (same family as trajectory evidence).",
        "Insufficient size/likelihood after title+teaser+confirming filing sets "
        f"seek_richer_source (planned next: {RICHER_SOURCE}); nothing is fetched yet.",
        "Do not promote a rule into the live path until confirmation_rate is promising "
        f"and later-filing n ≥ {MIN_CONFIRM_N}.",
    ]
    if len(indexed) < 13:
        notes.append(
            f"Archive history is thin ({len(indexed)} snapshots); 12w labels stay sparse."
        )

    journal = {
        "schema_version": SCHEMA_VERSION,
        "scope": "news_event_journal",
        "observe_only": True,
        "source_pool": SOURCE_POOL,
        "mode": mode,
        "extractor_version": EXTRACTOR_VERSION,
        "generated_at": generated_at,
        "cohort_ticker_count": len(cohort),
        "tickers_with_news": tickers_with_news,
        "article_count": articles_total,
        "issuer_reject_count": issuer_rejects,
        "event_count": len(events),
        "later_filing_available_count": later_avail,
        "confirmed_count": confirmed,
        "seek_richer_source_count": seek_richer,
        "per_ticker": per_ticker,
        "events": events,
        "notes": notes,
    }
    state = {
        "schema_version": SCHEMA_VERSION,
        "scope": "news_event_journal_state",
        "updated_at": generated_at,
        "mode_last_run": mode,
        "extractor_version": EXTRACTOR_VERSION,
        "ticker_watermarks": new_watermarks,
    }
    rules = {**rules, "generated_at": generated_at, "source_pool": SOURCE_POOL}

    write_json(data_dir / JOURNAL_FILENAME, journal, compact=False, compress=False)
    write_json(data_dir / RULES_FILENAME, rules, compact=False, compress=False)
    write_json(data_dir / STATE_FILENAME, state, compact=False, compress=False)
    (data_dir / REVIEW_MD_FILENAME).write_text(
        _format_review_markdown(journal, rules),
        encoding="utf-8",
    )
    return {
        "journal": journal,
        "rules": rules,
        "state": state,
        "paths": {
            "journal": str(data_dir / JOURNAL_FILENAME),
            "rules": str(data_dir / RULES_FILENAME),
            "state": str(data_dir / STATE_FILENAME),
            "review_md": str(data_dir / REVIEW_MD_FILENAME),
        },
    }


__all__ = [
    "JOURNAL_FILENAME",
    "REVIEW_MD_FILENAME",
    "RULES_FILENAME",
    "STATE_FILENAME",
    "FilingRow",
    "assess_evidence",
    "classify_headline",
    "extract_event_facts",
    "issuer_mentioned",
    "join_later_filing",
    "run_news_event_journal",
]
