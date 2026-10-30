"""Observe-only entry news polarity cite on buy-day (L650).

Joins existing offline news stores (phrase lexicon L225, event journal N90/N86,
per-ticker ``news_manifest``) into a PIT polarity label + durable cites for
``entry_blind`` cards. Never influences fills, knobs, strand A, or Package L.

Labels: ``structural_negative`` | ``improvement_path`` | ``mixed_or_unclear`` |
``no_usable_news`` (fail-closed when no PIT issuer news).

Recency lock (v0 — no influence-fade):
1. Hard PIT lookback ending at buy-day: ``DEFAULT_LOOKBACK_DAYS`` (= 90 calendar
   days). Articles outside the window are unused; if nothing remains →
   ``no_usable_news``.
2. No continuous fade score drives the polarity enum or any fill weight.
   Polarity stays discrete labels only.
3. Cite metadata may include ``age_days`` + freshness band
   ``recent`` (≤14d) / ``medium`` (≤45d) / ``stale`` (rest of window) for human
   review — never a multiplicative influence on decisions or sizing.
4. Exponential / parametric influence-fade into live or lab sizing is out of
   scope (parked; revisit when entry_blind polarity disagreement marks are thick).
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.news_event_journal import classify_headline, event_id, issuer_mentioned
from value_investor.news_phrase_trajectory import (
    _parse_dt,
    extract_phrases,
    load_news_manifest,
)
from value_investor.storage import read_json, resolve_json_path, write_json

SCHEMA_VERSION = 1
STORE_FILENAME = "entry_news_polarity.json"
SOURCE_ID = "lexicon_journal_v0"
OPS_DOC = "docs/ops/entry-news-polarity.md"
FINDING_TITLE = "Entry news polarity (observe)"
DEFAULT_DATA_DIR = Path("docs/data")
DEFAULT_LOOKBACK_DAYS = 90  # hard PIT window ending buy-day; not a fade curve
MAX_CITES = 5
# Cite freshness bands (display metadata only — never weights the label).
FRESHNESS_RECENT_DAYS = 14
FRESHNESS_MEDIUM_DAYS = 45
FRESHNESS_BANDS = frozenset({"recent", "medium", "stale"})

POLARITY_LABELS = frozenset(
    {
        "structural_negative",
        "improvement_path",
        "mixed_or_unclear",
        "no_usable_news",
    }
)

# Title-only hand lists — not a sentiment API. Lexicon lift alone never flips valence.
_STRUCTURAL_PHRASES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bgoing concern\b", re.I),
    re.compile(r"\bprofit warning\b", re.I),
    re.compile(r"\b(administration|administrators?)\b", re.I),
    re.compile(r"\bliquidat(?:e|es|ed|ion|ing)\b", re.I),
    re.compile(r"\bmaterial uncertainty\b", re.I),
    re.compile(r"\bcovenant breach\b", re.I),
    re.compile(r"\b(impairment|write[- ]?down)\b", re.I),
    re.compile(r"\b(fraud|investigation)\b", re.I),
    re.compile(r"\b(receivership|insolvency|bankrupt(?:cy|cies)?)\b", re.I),
    re.compile(r"\b(suspend(?:s|ed|ing)?|halt(?:s|ed|ing)?)\s+(trading|listing)\b", re.I),
)

_IMPROVEMENT_PHRASES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bcontract win\b", re.I),
    re.compile(r"\bwins?\s+(a\s+)?(major\s+)?contract\b", re.I),
    re.compile(r"\b(award|awarded)\s+(a\s+)?(major\s+)?(contract|tender)\b", re.I),
    re.compile(r"\b(upgrade|upgraded|upgrades)\b", re.I),
    re.compile(r"\b(recovery|recovering|recovered)\b", re.I),
    re.compile(r"\bturnaround\b", re.I),
    re.compile(r"\brefinanc(?:e|es|ed|ing)\b", re.I),
    re.compile(r"\bdebt reduction\b", re.I),
    re.compile(r"\bnew (credit )?facility\b", re.I),
    re.compile(r"\b(positive|encouraging)\s+(trading|outlook|update)\b", re.I),
)

_RESIGN_RE = re.compile(
    r"\b(resign|resigns|resigned|steps? down|departure|exit)\b",
    re.I,
)
_APPOINT_RE = re.compile(
    r"\b(appoint|appointed|appoints|named|names|new|interim|succeeds|succession)\b",
    re.I,
)
_CONTRACT_WIN_RE = re.compile(
    r"\b(win|won|wins|award|awarded)\b",
    re.I,
)
_CONTRACT_LOSS_RE = re.compile(
    r"\b(loss|lost|loses)\b",
    re.I,
)
_DIVEST_RE = re.compile(
    r"\b(disposal|divest(?:s|ed|iture|ment)?)\b",
    re.I,
)
_STRATEGY_EXIT_RE = re.compile(
    r"\b(exit|exits|exiting|wind[- ]?down|close|closes|closing)\b.{0,40}\b(division|unit|business)\b|"
    r"\b(division|unit|business)\b.{0,40}\b(exit|exits|exiting|wind[- ]?down|close|closes|closing)\b",
    re.I,
)


def _empty_polarity(
    *,
    asof: str | None,
    window_start: str | None = None,
    counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    return {
        "label": "no_usable_news",
        "asof": asof,
        "window_start": window_start,
        "join_ok": False,
        "influences_live": False,
        "source": SOURCE_ID,
        "cites": [],
        "counts": counts
        or {
            "articles_pit": 0,
            "journal_hits": 0,
            "lexicon_hits": 0,
            "structural_hints": 0,
            "improvement_hints": 0,
        },
    }


def load_phrase_lexicon(data_dir: Path) -> dict[str, Any]:
    path = resolve_json_path(Path(data_dir) / "news_phrase_lexicon.json")
    if path is None:
        return {"phrases": []}
    payload = read_json(path)
    return payload if isinstance(payload, dict) else {"phrases": []}


def lexicon_phrase_index(lexicon: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Map phrase string → lexicon row for O(1) join."""
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(lexicon, dict):
        return out
    for row in lexicon.get("phrases") or []:
        if not isinstance(row, dict):
            continue
        phrase = str(row.get("phrase") or "").strip().lower()
        if phrase:
            out[phrase] = row
    return out


def load_journal_events_by_ticker(data_dir: Path) -> dict[str, list[dict[str, Any]]]:
    path = resolve_json_path(Path(data_dir) / "news_event_journal.json")
    by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if path is None:
        return {}
    payload = read_json(path)
    if not isinstance(payload, dict):
        return {}
    events = payload.get("events") or payload.get("records") or []
    if not isinstance(events, list):
        return {}
    for row in events:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").strip()
        if ticker:
            by_ticker[ticker].append(row)
    return dict(by_ticker)


def freshness_band(age_days: int) -> str:
    """Map age within the hard window to a display band. Never a fill weight."""
    if age_days <= FRESHNESS_RECENT_DAYS:
        return "recent"
    if age_days <= FRESHNESS_MEDIUM_DAYS:
        return "medium"
    return "stale"


def cite_recency_meta(*, published_at: str | None, asof_day) -> dict[str, Any]:
    """Optional cite metadata: ``age_days`` + ``freshness`` band. No fade score."""
    pub = _parse_dt(published_at) if published_at else None
    if pub is None:
        return {"age_days": None, "freshness": None}
    age = (asof_day - pub.date()).days
    if age < 0:
        # Should not happen after PIT filter; fail-closed omit.
        return {"age_days": None, "freshness": None}
    return {"age_days": age, "freshness": freshness_band(age)}


def pit_manifest_articles(
    data_dir: Path,
    ticker: str,
    *,
    asof: str,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> list[dict[str, Any]]:
    """Articles with ``published_at.date()`` in ``(asof - lookback, asof]``.

    Hard window only — items outside are dropped (no partial fade). Never after asof.
    """
    asof_dt = _parse_dt(asof)
    if asof_dt is None:
        # Allow bare YYYY-MM-DD
        try:
            asof_dt = datetime.fromisoformat(str(asof)[:10]).replace(tzinfo=UTC)
        except ValueError:
            return []
    asof_day = asof_dt.date()
    start_day = asof_day - timedelta(days=max(0, int(lookback_days)))
    out: list[dict[str, Any]] = []
    for article in load_news_manifest(Path(data_dir), ticker):
        published = _parse_dt(str(article.get("published_at") or "") or None)
        if published is None:
            continue
        day = published.date()
        if day > asof_day:
            continue
        if day <= start_day:
            continue
        out.append(article)
    out.sort(key=lambda row: str(row.get("published_at") or ""), reverse=True)
    return out


def _valence_from_title(
    title: str,
    *,
    event_type: str | None,
) -> str | None:
    """Return structural_negative | improvement_path | None for one title."""
    text = (title or "").strip()
    if not text:
        return None
    structural = any(p.search(text) for p in _STRUCTURAL_PHRASES)
    improvement = any(p.search(text) for p in _IMPROVEMENT_PHRASES)

    if event_type == "contract":
        if _CONTRACT_LOSS_RE.search(text) and not _CONTRACT_WIN_RE.search(text):
            structural = True
        if _CONTRACT_WIN_RE.search(text) and not _CONTRACT_LOSS_RE.search(text):
            improvement = True
    elif event_type == "leadership":
        if _RESIGN_RE.search(text) and not _APPOINT_RE.search(text):
            structural = True
        # Appoint alone is weak — do not flip to improvement without phrase hit.
    elif event_type == "m_and_a":
        if _DIVEST_RE.search(text):
            structural = True
    elif event_type == "strategy":
        if _STRATEGY_EXIT_RE.search(text):
            structural = True

    if structural and improvement:
        return None  # conflicting on one title → counted both ways at aggregate
    if structural:
        return "structural_negative"
    if improvement:
        return "improvement_path"
    # Dual-hit on same title: treat as both hints for aggregation
    if any(p.search(text) for p in _STRUCTURAL_PHRASES) and any(
        p.search(text) for p in _IMPROVEMENT_PHRASES
    ):
        return None
    return None


def _title_has_both_valences(title: str) -> bool:
    text = (title or "").strip()
    return any(p.search(text) for p in _STRUCTURAL_PHRASES) and any(
        p.search(text) for p in _IMPROVEMENT_PHRASES
    )


def derive_entry_news_polarity(
    *,
    ticker: str,
    entry_at: str | None,
    name: str | None = None,
    data_dir: Path,
    lexicon: dict[str, Any] | None = None,
    journal_by_ticker: dict[str, list[dict[str, Any]]] | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict[str, Any]:
    """Fail-closed polarity + cites. ``influences_live=false``."""
    asof = str(entry_at or "")[:10] or None
    if not ticker or not asof:
        return _empty_polarity(asof=asof)

    asof_dt = _parse_dt(asof) or datetime.fromisoformat(asof).replace(tzinfo=UTC)
    window_start = (asof_dt.date() - timedelta(days=max(0, int(lookback_days)))).isoformat()

    articles = pit_manifest_articles(
        Path(data_dir),
        ticker,
        asof=asof,
        lookback_days=lookback_days,
    )
    usable: list[dict[str, Any]] = []
    for article in articles:
        title = str(article.get("title") or "").strip()
        summary = str(article.get("summary") or "")
        if not title:
            continue
        if not issuer_mentioned(
            title,
            summary,
            company_name=name,
            ticker=ticker,
        ):
            continue
        usable.append(article)

    if not usable:
        return _empty_polarity(
            asof=asof,
            window_start=window_start,
            counts={
                "articles_pit": 0,
                "journal_hits": 0,
                "lexicon_hits": 0,
                "structural_hints": 0,
                "improvement_hints": 0,
            },
        )

    lex_index = lexicon_phrase_index(
        lexicon if lexicon is not None else load_phrase_lexicon(Path(data_dir))
    )
    journal_rows = (
        journal_by_ticker.get(ticker)
        if isinstance(journal_by_ticker, dict)
        else load_journal_events_by_ticker(Path(data_dir)).get(ticker)
    ) or []
    journal_by_article: dict[str, dict[str, Any]] = {}
    for row in journal_rows:
        if not isinstance(row, dict):
            continue
        pub = _parse_dt(str(row.get("published_at") or "") or None)
        if pub is None or pub.date() > asof_dt.date():
            continue  # PIT: ignore post-buy journal rows
        aid = str(row.get("article_id") or "").strip()
        if aid:
            journal_by_article[aid] = row

    structural_n = 0
    improvement_n = 0
    journal_hits = 0
    lexicon_hits = 0
    cites: list[dict[str, Any]] = []

    for article in usable:
        title = str(article.get("title") or "").strip()
        article_id = str(article.get("id") or "").strip() or None
        published_at = str(article.get("published_at") or "").strip() or None
        classified = classify_headline(title)
        event_type = classified.get("primary_event_type")
        journal_row = journal_by_article.get(article_id or "") if article_id else None
        if journal_row is not None:
            journal_hits += 1
            event_type = journal_row.get("primary_event_type") or event_type

        both = _title_has_both_valences(title)
        valence = _valence_from_title(title, event_type=str(event_type) if event_type else None)
        if both:
            structural_n += 1
            improvement_n += 1
            valence_hint = None
        elif valence == "structural_negative":
            structural_n += 1
            valence_hint = "structural_negative"
        elif valence == "improvement_path":
            improvement_n += 1
            valence_hint = "improvement_path"
        else:
            valence_hint = None

        phrases = extract_phrases(title)
        lex_hit: dict[str, Any] | None = None
        for phrase in phrases:
            row = lex_index.get(phrase)
            if row is not None:
                lexicon_hits += 1
                lex_hit = row
                break
        # Lexicon status alone never sets valence — cite metadata only.

        recency = cite_recency_meta(published_at=published_at, asof_day=asof_dt.date())

        if valence_hint is None and event_type is None and lex_hit is None and not both:
            # Keep weak issuer headlines for mixed_or_unclear aggregation only.
            if len(cites) >= MAX_CITES:
                continue
            cites.append(
                {
                    "kind": "headline",
                    "ticker": ticker,
                    "published_at": published_at,
                    "article_id": article_id,
                    "event_id": None,
                    "title": title[:220],
                    "event_type": None,
                    "phrase": None,
                    "lexicon_status": None,
                    "valence_hint": None,
                    "age_days": recency["age_days"],
                    "freshness": recency["freshness"],
                }
            )
            continue

        kind = (
            "journal"
            if journal_row is not None
            else (
                "lexicon"
                if lex_hit is not None and valence_hint is None and event_type is None
                else "headline_phrase"
            )
        )
        if event_type is not None and journal_row is None:
            kind = "headline_phrase"
        eid = None
        if journal_row is not None:
            eid = str(journal_row.get("event_id") or "").strip() or None
        if eid is None and published_at:
            pub_dt = _parse_dt(published_at)
            if pub_dt is not None:
                eid = event_id(ticker, pub_dt, title)

        if len(cites) < MAX_CITES and (
            valence_hint is not None or event_type is not None or lex_hit is not None or both
        ):
            cites.append(
                {
                    "kind": kind,
                    "ticker": ticker,
                    "published_at": published_at,
                    "article_id": article_id,
                    "event_id": eid,
                    "title": title[:220],
                    "event_type": str(event_type) if event_type else None,
                    "phrase": str(lex_hit.get("phrase")) if lex_hit else None,
                    "lexicon_status": str(lex_hit.get("status")) if lex_hit else None,
                    "valence_hint": valence_hint
                    if valence_hint
                    else ("mixed_or_unclear" if both else None),
                    "age_days": recency["age_days"],
                    "freshness": recency["freshness"],
                }
            )

    if structural_n and improvement_n:
        label = "mixed_or_unclear"
    elif structural_n:
        label = "structural_negative"
    elif improvement_n:
        label = "improvement_path"
    else:
        # Issuer PIT headlines exist but no valence hint → mixed, not invented bullish/bearish.
        label = "mixed_or_unclear"

    # Prefer cites that carry valence/event; keep up to MAX_CITES already enforced.
    return {
        "label": label,
        "asof": asof,
        "window_start": window_start,
        "join_ok": True,
        "influences_live": False,
        "source": SOURCE_ID,
        "cites": cites[:MAX_CITES],
        "counts": {
            "articles_pit": len(usable),
            "journal_hits": journal_hits,
            "lexicon_hits": lexicon_hits,
            "structural_hints": structural_n,
            "improvement_hints": improvement_n,
        },
    }


def bind_entry_news_polarity(
    item: dict[str, Any],
    *,
    data_dir: Path,
    lexicon: dict[str, Any] | None = None,
    journal_by_ticker: dict[str, list[dict[str, Any]]] | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict[str, Any]:
    """Attach ``item['entry_news_polarity']``; never mutates ``buy_decision``."""
    polarity = derive_entry_news_polarity(
        ticker=str(item.get("ticker") or "").strip(),
        entry_at=str(item.get("entry_at") or item.get("opened_at") or "") or None,
        name=str(item.get("name") or "").strip() or None,
        data_dir=Path(data_dir),
        lexicon=lexicon,
        journal_by_ticker=journal_by_ticker,
        lookback_days=lookback_days,
    )
    item["entry_news_polarity"] = polarity
    return item


def build_entry_news_polarity_panel(
    *,
    data_dir: Path,
    cards: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Cohort rollup for utilization / ops finding (observe-only).

    ``data_dir`` kept for API symmetry with bind/persist callers; panel is
    derived from already-bound card fields.
    """
    rows = cards if cards is not None else []
    label_counts: dict[str, int] = {lab: 0 for lab in sorted(POLARITY_LABELS)}
    for card in rows:
        if not isinstance(card, dict):
            continue
        pol = card.get("entry_news_polarity")
        if not isinstance(pol, dict):
            continue
        label = str(pol.get("label") or "no_usable_news")
        if label not in label_counts:
            label = "no_usable_news"
        label_counts[label] = label_counts.get(label, 0) + 1
    usable = sum(n for lab, n in label_counts.items() if lab != "no_usable_news")
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "observe_only": True,
        "influences_live": False,
        "package": "M",
        "source": SOURCE_ID,
        "ops_doc": OPS_DOC,
        "card_count": len(rows),
        "cards_with_usable_news": usable,
        "no_usable_news": label_counts.get("no_usable_news", 0),
        "label_counts": label_counts,
        # N236 MFT B-cell for catalyst/news stays deferred — polarity instrument is L650.
        "n236_mft_b_cell": "deferred_until_l650_cohort; see L650 / N236",
    }


def persist_entry_news_polarity_panel(
    payload: dict[str, Any],
    *,
    data_dir: Path,
) -> Path:
    path = Path(data_dir) / STORE_FILENAME
    write_json(path, payload, compact=False)
    return path


def ops_findings_from_entry_news_polarity(
    payload: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return [
            {
                "severity": "info",
                "category": "research",
                "title": FINDING_TITLE,
                "summary": (
                    "Entry news polarity panel missing — fail-closed; cards show "
                    "no_usable_news until bind refresh. influences_live=false."
                ),
                "auto_fixable": False,
            }
        ]
    usable = int(payload.get("cards_with_usable_news") or 0)
    none = int(payload.get("no_usable_news") or 0)
    total = int(payload.get("card_count") or 0)
    counts = payload.get("label_counts") if isinstance(payload.get("label_counts"), dict) else {}
    return [
        {
            "severity": "info",
            "category": "research",
            "title": FINDING_TITLE,
            "summary": (
                f"Buy-day PIT polarity on entry_blind: {usable}/{total} cards with usable "
                f"news cites; {none} no_usable_news. "
                f"Labels={counts}. Observe-only (influences_live=false); not Package L / "
                f"not strand-A veto. See {OPS_DOC}."
            ),
            "auto_fixable": False,
        }
    ]


__all__ = [
    "DEFAULT_DATA_DIR",
    "DEFAULT_LOOKBACK_DAYS",
    "FINDING_TITLE",
    "FRESHNESS_BANDS",
    "FRESHNESS_MEDIUM_DAYS",
    "FRESHNESS_RECENT_DAYS",
    "OPS_DOC",
    "POLARITY_LABELS",
    "SCHEMA_VERSION",
    "SOURCE_ID",
    "STORE_FILENAME",
    "bind_entry_news_polarity",
    "build_entry_news_polarity_panel",
    "cite_recency_meta",
    "derive_entry_news_polarity",
    "freshness_band",
    "lexicon_phrase_index",
    "load_journal_events_by_ticker",
    "load_phrase_lexicon",
    "ops_findings_from_entry_news_polarity",
    "persist_entry_news_polarity_panel",
    "pit_manifest_articles",
]
