"""Local unknown-unknown scan over filings we already fetched.

Walks buy∪boundary ``filings_index.json`` headlines on disk. Drops routine RNS,
classifies known event types, and keeps leftover official headlines as candidate
classes. No HTTP. Develops the closed news-event taxonomy without extra calls.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.news_event_journal import classify_headline
from value_investor.news_phrase_trajectory import select_buy_boundary_cohort
from value_investor.storage import read_json, resolve_json_path, write_json

SCHEMA_VERSION = 1
UNKNOWN_FILENAME = "filing_event_unknowns.json"
REVIEW_MD_FILENAME = "filing_event_unknowns_review.md"

MIN_PHRASE_TICKERS = 3
MAX_CANDIDATES = 80
MAX_PHRASES = 40

# Routine RNS / CH labels that are not material-event surprises.
_ROUTINE = re.compile(
    r"pdmr|person discharging|total voting rights|block listing|"
    r"transaction in own shares|treasury share|holding\(s\) in company|"
    r"holdings in company|director/?pdmr|scrip dividend|notice of agm|"
    r"result of (?:the )?(?:agm|gm)|proxy form|restoration of listing|"
    r"admission of shares|issue of (?:equity|shares)|director shareholding|"
    r"companies house accounts|accounts-with-accounts|"
    r"dividend timetable|interim dividend|final dividend|"
    r"notification of major|rule 2\.9|form 8\.|schedule 10|"
    r"voting rights|buy[- ]?back programme|share buyback|"
    r"final results|interim results|half[- ]year|full year|annual report|"
    r"trading update|trading statement|preliminary results|"
    r"notice of (?:h1 |h2 |fy |q[1-4] )?results|analyst and retail|"
    r"investor presentation|ltip|sharesave|long term incentive|"
    r"grant of options|vesting of|"
    r"annual financial report|director declaration|"
    r"admission (?:to )?trading|result of the \d{4} agm|"
    r"annual general meeting|"
    r"allowlist document|across markets|"
    r"notice of \d{4} annual results",
    flags=re.I,
)

_STOP = frozenset(
    """
    a an the and or but if in on at to for of from with by as is are was were
    plc ltd limited group company companies holdings investegate via under
    """.split()
)


def is_routine_filing_headline(headline: str) -> bool:
    return bool(_ROUTINE.search(headline or ""))


def _phrases(headline: str) -> list[str]:
    tokens = [
        tok for tok in re.findall(r"[a-z][a-z'-]{3,}", (headline or "").lower()) if tok not in _STOP
    ]
    out: list[str] = []
    seen: set[str] = set()
    for index in range(len(tokens) - 1):
        phrase = f"{tokens[index]} {tokens[index + 1]}"
        if phrase not in seen:
            seen.add(phrase)
            out.append(phrase)
    for index in range(len(tokens) - 2):
        phrase = f"{tokens[index]} {tokens[index + 1]} {tokens[index + 2]}"
        if phrase not in seen:
            seen.add(phrase)
            out.append(phrase)
    return out


def _format_review(payload: dict[str, Any]) -> str:
    lines = [
        "# Filing event unknowns (observe-only, no extra calls)",
        "",
        f"- Generated: `{payload.get('generated_at')}`",
        f"- Filings walked: **{payload.get('filing_count')}**",
        f"- Routine dropped: **{payload.get('routine_count')}**",
        f"- Known event class: **{payload.get('known_event_count')}**",
        f"- Leftover candidates: **{payload.get('unknown_count')}**",
        "",
        "## Recurring leftover phrases",
        "",
        "Phrases that appear in leftover official headlines on ≥3 tickers.",
        "These are taxonomy holes — not live scores.",
        "",
    ]
    phrases = payload.get("phrases") or []
    if not phrases:
        lines.append("_No leftover phrase cleared the ticker gate._")
    else:
        lines.append("| n tickers | n headlines | phrase |")
        lines.append("|---:|---:|---|")
        for row in phrases[:20]:
            lines.append(
                f"| {row.get('ticker_count')} | {row.get('headline_count')} | "
                f"`{row.get('phrase')}` |"
            )
    lines.extend(["", "## Sample leftover headlines", ""])
    samples = payload.get("samples") or []
    if not samples:
        lines.append("_No leftover official headlines._")
    else:
        lines.append("| ticker | period | headline |")
        lines.append("|---|---|---|")
        for row in samples:
            title = str(row.get("headline") or "").replace("|", "/")
            lines.append(f"| `{row.get('ticker')}` | {row.get('period')} | {title} |")
    lines.extend(["", "## Notes", ""])
    for note in payload.get("notes") or []:
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)


def run_filing_event_discovery(
    data_dir: Path,
    *,
    tickers: list[str] | None = None,
) -> dict[str, Any]:
    """Scan on-disk filing headlines for classes the news journal does not cover."""
    data_dir = Path(data_dir)
    cohort = select_buy_boundary_cohort(data_dir)
    if tickers:
        wanted = {item.strip() for item in tickers if item.strip()}
        cohort = [row for row in cohort if row["ticker"] in wanted]

    filing_count = 0
    routine_count = 0
    known_count = 0
    candidates: list[dict[str, Any]] = []
    phrase_tickers: dict[str, set[str]] = defaultdict(set)
    phrase_hits: Counter[str] = Counter()

    for member in cohort:
        ticker = member["ticker"]
        index_path = resolve_json_path(
            data_dir / "research" / ticker / "sources" / "filings" / "filings_index.json"
        )
        if index_path is None:
            continue
        try:
            payload = read_json(index_path)
        except (OSError, ValueError, TypeError):
            continue
        for row in payload.get("filings") or []:
            if not isinstance(row, dict):
                continue
            filing_count += 1
            headline = str(row.get("headline") or row.get("title") or "").strip()
            if not headline:
                continue
            if is_routine_filing_headline(headline):
                routine_count += 1
                continue
            classified = classify_headline(headline)
            if classified["primary_event_type"]:
                known_count += 1
                continue
            item = {
                "ticker": ticker,
                "name": member.get("name"),
                "period": row.get("period") or "other",
                "source": row.get("source"),
                "published_at": row.get("published_at"),
                "headline": headline[:220],
                "has_body": bool(row.get("has_body")),
            }
            candidates.append(item)
            for phrase in _phrases(headline):
                phrase_tickers[phrase].add(ticker)
                phrase_hits[phrase] += 1

    ranked = []
    for phrase, tickers_hit in phrase_tickers.items():
        if len(tickers_hit) < MIN_PHRASE_TICKERS:
            continue
        ranked.append(
            {
                "phrase": phrase,
                "ticker_count": len(tickers_hit),
                "headline_count": phrase_hits[phrase],
                "status": "watch",
            }
        )
    ranked.sort(key=lambda row: (-row["ticker_count"], -row["headline_count"], row["phrase"]))
    ranked = ranked[:MAX_PHRASES]
    samples = candidates[:MAX_CANDIDATES]
    generated_at = datetime.now(UTC).isoformat()
    payload = {
        "schema_version": SCHEMA_VERSION,
        "scope": "filing_event_unknowns",
        "observe_only": True,
        "extra_http": False,
        "generated_at": generated_at,
        "cohort_ticker_count": len(cohort),
        "filing_count": filing_count,
        "routine_count": routine_count,
        "known_event_count": known_count,
        "unknown_count": len(candidates),
        "phrases": ranked,
        "samples": samples,
        "notes": [
            "Uses filings_index headlines already on disk — no extra downloads.",
            "Routine RNS (PDMR, TVR, AGM, LTIP, CH accounts labels) are dropped.",
            "Known news-event classes are counted then skipped.",
            "Leftover recurring phrases are taxonomy holes for the event journal.",
            "Does not write screen weights or fetch Guardian / article HTML.",
        ],
    }
    write_json(data_dir / UNKNOWN_FILENAME, payload, compact=False, compress=False)
    (data_dir / REVIEW_MD_FILENAME).write_text(_format_review(payload), encoding="utf-8")
    return payload


__all__ = [
    "REVIEW_MD_FILENAME",
    "UNKNOWN_FILENAME",
    "is_routine_filing_headline",
    "run_filing_event_discovery",
]
