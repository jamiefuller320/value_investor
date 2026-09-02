"""Offline news-phrase ↔ trajectory panel (buy / boundary cohort).

Walks each ticker chronologically from earliest headline, joins phrases to
archive-based forward returns (and nearby trajectory transitions), then builds
a walk-forward lexicon with a simple self-improve gate. Observe-only.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.backtest import RunSnapshot, load_run_snapshots
from value_investor.paper_fund import BUY_SIGNALS
from value_investor.storage import read_json, resolve_json_path, write_json
from value_investor.trajectory_evidence import (
    BOUNDARY_FILENAME,
    FORWARD_HORIZONS_WEEKS,
    TRANSITIONS_FILENAME,
)

SCHEMA_VERSION = 1
PANEL_FILENAME = "news_phrase_trajectory.json"
LEXICON_FILENAME = "news_phrase_lexicon.json"
STATE_FILENAME = "news_phrase_trajectory_state.json"
REVIEW_MD_FILENAME = "news_phrase_trajectory_review.md"

SOURCE_POOL = "buy_boundary"
DEFAULT_TRAIN_FRACTION = 0.7
DEFAULT_MIN_TRAIN_COUNT = 4
DEFAULT_MIN_TOKEN_LEN = 3
DEFAULT_MAX_PHRASES = 80
TRANSITION_LOOKBACK_DAYS = 14
PROMOTE_LIFT = 0.02
DEMOTE_LIFT = -0.005

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9'-]*[a-z0-9]|[a-z0-9]+")
_STOPWORDS = frozenset(
    """
    a an the and or but if in on at to for of from with by as is are was were be
    been being it its this that these those not no nor so than then too very can
    could should would will just about into over after before under again further
    once here there when where why how all any both each few more most other some
    such only own same s t don now new says say said week month year today
    yesterday plc ltd limited group company companies shares share stock stocks
    market markets london ftse uk british england update updates trading report
    reports results interim annual half full q1 q2 q3 q4 fy h1 h2
    """.split()
)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def _tokenize(text: str) -> list[str]:
    return [token for token in _TOKEN_RE.findall(text.lower()) if token]


def _issuer_stop_tokens(ticker: str, name: str | None) -> set[str]:
    tokens: set[str] = set()
    epic = ticker.split(".")[0].lower()
    if epic:
        tokens.add(epic)
    for token in _tokenize(name or ""):
        if len(token) >= DEFAULT_MIN_TOKEN_LEN:
            tokens.add(token)
    return tokens


def extract_phrases(
    title: str,
    summary: str = "",
    *,
    issuer_stops: set[str] | None = None,
    min_token_len: int = DEFAULT_MIN_TOKEN_LEN,
) -> list[str]:
    """Extract filtered unigrams + bigrams + trigrams from headline text."""
    stops = _STOPWORDS | (issuer_stops or set())
    tokens = [
        token
        for token in _tokenize(f"{title} {summary}")
        if len(token) >= min_token_len and token not in stops and not token.isdigit()
    ]
    if not tokens:
        return []
    phrases: list[str] = []
    seen: set[str] = set()

    def _add(phrase: str) -> None:
        if phrase not in seen:
            seen.add(phrase)
            phrases.append(phrase)

    for token in tokens:
        _add(token)
    for index in range(len(tokens) - 1):
        _add(f"{tokens[index]} {tokens[index + 1]}")
    for index in range(len(tokens) - 2):
        _add(f"{tokens[index]} {tokens[index + 1]} {tokens[index + 2]}")
    return phrases


def load_news_manifest(data_dir: Path, ticker: str) -> list[dict[str, Any]]:
    path = resolve_json_path(data_dir / "research" / ticker / "sources" / "news_manifest.json")
    if path is None:
        return []
    payload = read_json(path)
    articles = payload.get("articles") if isinstance(payload, dict) else payload
    if not isinstance(articles, list):
        return []
    return [row for row in articles if isinstance(row, dict)]


def select_buy_boundary_cohort(data_dir: Path) -> list[dict[str, Any]]:
    """Buy / strong_buy from latest screen ∪ boundary-watch panel."""
    latest_path = resolve_json_path(data_dir / "latest.json")
    if latest_path is None:
        raise FileNotFoundError(data_dir / "latest.json")
    latest = read_json(latest_path)
    by_ticker: dict[str, dict[str, Any]] = {}

    for row in latest.get("reports") or []:
        ticker = str(row.get("ticker") or "").strip()
        if not ticker:
            continue
        signal = str(row.get("signal") or "").strip().lower()
        if signal not in BUY_SIGNALS:
            continue
        by_ticker[ticker] = {
            "ticker": ticker,
            "name": row.get("name"),
            "signal": signal,
            "conviction_score": row.get("conviction_score"),
            "sector": row.get("sector"),
            "cohort_tags": ["buy_tier"],
        }

    boundary_path = resolve_json_path(data_dir / BOUNDARY_FILENAME)
    if boundary_path is not None:
        boundary = read_json(boundary_path)
        for row in boundary.get("panel") or []:
            ticker = str(row.get("ticker") or "").strip()
            if not ticker:
                continue
            existing = by_ticker.get(ticker)
            tags = list(existing["cohort_tags"]) if existing else []
            if "boundary" not in tags:
                tags.append("boundary")
            by_ticker[ticker] = {
                "ticker": ticker,
                "name": row.get("name") or (existing or {}).get("name"),
                "signal": row.get("signal") or (existing or {}).get("signal"),
                "conviction_score": (
                    row.get("conviction_score")
                    if row.get("conviction_score") is not None
                    else (existing or {}).get("conviction_score")
                ),
                "sector": row.get("sector") or (existing or {}).get("sector"),
                "cohort_tags": tags,
                "core_boundary_tags": list(row.get("core_boundary_tags") or []),
            }

    return [by_ticker[key] for key in sorted(by_ticker)]


def _snapshot_index(snapshots: list[RunSnapshot]) -> list[tuple[datetime, RunSnapshot]]:
    indexed: list[tuple[datetime, RunSnapshot]] = []
    for snap in sorted(snapshots, key=lambda item: item.run_at):
        when = _parse_dt(snap.run_at)
        if when is not None:
            indexed.append((when, snap))
    return indexed


def _forward_returns_from_archive(
    ticker: str,
    article_at: datetime,
    indexed: list[tuple[datetime, RunSnapshot]],
    horizons: tuple[int, ...] = FORWARD_HORIZONS_WEEKS,
) -> dict[str, float | None]:
    """Map article time → first archive at/after publish, then +N archive steps."""
    entry_index: int | None = None
    for index, (when, _snap) in enumerate(indexed):
        if when >= article_at:
            entry_index = index
            break
    out: dict[str, float | None] = {f"forward_return_{weeks}w": None for weeks in horizons}
    if entry_index is None:
        return out
    p0 = indexed[entry_index][1].prices.get(ticker)
    if p0 is None or float(p0) <= 0:
        return out
    for weeks in horizons:
        forward_index = entry_index + weeks
        if forward_index >= len(indexed):
            continue
        p1 = indexed[forward_index][1].prices.get(ticker)
        if p1 is None or float(p1) <= 0:
            continue
        out[f"forward_return_{weeks}w"] = round((float(p1) / float(p0)) - 1.0, 6)
    return out


def _load_transitions_by_ticker(data_dir: Path) -> dict[str, list[dict[str, Any]]]:
    path = resolve_json_path(data_dir / TRANSITIONS_FILENAME)
    if path is None:
        return {}
    payload = read_json(path)
    by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in payload.get("events") or []:
        ticker = str(event.get("ticker") or "").strip()
        if ticker:
            by_ticker[ticker].append(event)
    for events in by_ticker.values():
        events.sort(key=lambda row: str(row.get("week_to") or ""))
    return dict(by_ticker)


def _nearby_transition(
    article_at: datetime,
    events: list[dict[str, Any]],
    *,
    lookback_days: int = TRANSITION_LOOKBACK_DAYS,
) -> dict[str, Any] | None:
    window_end = article_at + timedelta(days=lookback_days)
    best: dict[str, Any] | None = None
    best_delta: timedelta | None = None
    for event in events:
        week_to = _parse_dt(str(event.get("week_to") or ""))
        if week_to is None:
            continue
        if article_at <= week_to <= window_end:
            delta = week_to - article_at
            if best_delta is None or delta < best_delta:
                best = event
                best_delta = delta
    return best


@dataclass(frozen=True)
class PhraseObservation:
    ticker: str
    article_id: str
    published_at: datetime
    phrase: str
    ngram: int
    forward_return_4w: float | None
    forward_return_8w: float | None
    forward_return_12w: float | None
    transition_key: str | None
    transition_direction: str | None


def build_observations_for_ticker(
    *,
    ticker: str,
    name: str | None,
    articles: list[dict[str, Any]],
    indexed_snapshots: list[tuple[datetime, RunSnapshot]],
    transitions: list[dict[str, Any]],
) -> list[PhraseObservation]:
    issuer_stops = _issuer_stop_tokens(ticker, name)
    observations: list[PhraseObservation] = []
    for article in sorted(articles, key=lambda row: str(row.get("published_at") or "")):
        published_at = _parse_dt(str(article.get("published_at") or ""))
        if published_at is None:
            continue
        phrases = extract_phrases(
            str(article.get("title") or ""),
            str(article.get("summary") or ""),
            issuer_stops=issuer_stops,
        )
        if not phrases:
            continue
        forwards = _forward_returns_from_archive(ticker, published_at, indexed_snapshots)
        nearby = _nearby_transition(published_at, transitions)
        article_id = str(article.get("id") or f"{ticker}:{published_at.isoformat()}")
        for phrase in phrases:
            observations.append(
                PhraseObservation(
                    ticker=ticker,
                    article_id=article_id,
                    published_at=published_at,
                    phrase=phrase,
                    ngram=len(phrase.split()),
                    forward_return_4w=forwards.get("forward_return_4w"),
                    forward_return_8w=forwards.get("forward_return_8w"),
                    forward_return_12w=forwards.get("forward_return_12w"),
                    transition_key=(nearby or {}).get("transition_key"),
                    transition_direction=(nearby or {}).get("direction"),
                )
            )
    return observations


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 6)


def _sign_hit_rate(values: list[float], *, bullish: bool) -> float | None:
    if not values:
        return None
    hits = sum(1 for value in values if (value > 0 if bullish else value < 0))
    return round(hits / len(values), 4)


def _phrase_stats(
    observations: list[PhraseObservation],
    *,
    baseline_4w: float | None,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[PhraseObservation]] = defaultdict(list)
    for row in observations:
        grouped[row.phrase].append(row)

    rows: list[dict[str, Any]] = []
    for phrase, items in grouped.items():
        rets_4 = [float(x.forward_return_4w) for x in items if x.forward_return_4w is not None]
        rets_8 = [float(x.forward_return_8w) for x in items if x.forward_return_8w is not None]
        rets_12 = [float(x.forward_return_12w) for x in items if x.forward_return_12w is not None]
        mean_4 = _mean(rets_4)
        lift_4 = None if mean_4 is None or baseline_4w is None else round(mean_4 - baseline_4w, 6)
        tickers = sorted({item.ticker for item in items})
        rows.append(
            {
                "phrase": phrase,
                "ngram": items[0].ngram,
                "article_count": len({item.article_id for item in items}),
                "observation_count": len(items),
                "ticker_count": len(tickers),
                "tickers_sample": tickers[:12],
                "mean_forward_return_4w": mean_4,
                "mean_forward_return_8w": _mean(rets_8),
                "mean_forward_return_12w": _mean(rets_12),
                "baseline_forward_return_4w": baseline_4w,
                "lift_vs_baseline_4w": lift_4,
                "up_hit_rate_4w": _sign_hit_rate(rets_4, bullish=True),
                "down_hit_rate_4w": _sign_hit_rate(rets_4, bullish=False),
                "labeled_4w_count": len(rets_4),
                "nearby_upgrade_count": sum(
                    1 for item in items if item.transition_direction == "upgrade"
                ),
                "nearby_downgrade_count": sum(
                    1 for item in items if item.transition_direction == "downgrade"
                ),
            }
        )
    return rows


def _rank_phrases(rows: list[dict[str, Any]], *, min_train_count: int) -> list[dict[str, Any]]:
    eligible = [
        row
        for row in rows
        if int(row.get("labeled_4w_count") or 0) >= min_train_count
        and int(row.get("ticker_count") or 0) >= 2
    ]

    def sort_key(row: dict[str, Any]) -> tuple[float, float, int]:
        lift = abs(float(row.get("lift_vs_baseline_4w") or 0.0))
        labeled = int(row.get("labeled_4w_count") or 0)
        return (lift * math.log1p(labeled), lift, labeled)

    ranked = sorted(eligible, key=sort_key, reverse=True)
    for index, row in enumerate(ranked, start=1):
        row["rank"] = index
        lift = row.get("lift_vs_baseline_4w")
        if lift is None:
            row["status"] = "watch"
        elif float(lift) >= PROMOTE_LIFT:
            row["status"] = "promoted"
        elif float(lift) <= DEMOTE_LIFT:
            row["status"] = "demoted"
        else:
            row["status"] = "watch"
    return ranked


def walk_forward_lexicon(
    observations: list[PhraseObservation],
    *,
    train_fraction: float = DEFAULT_TRAIN_FRACTION,
    min_train_count: int = DEFAULT_MIN_TRAIN_COUNT,
) -> dict[str, Any]:
    """Mine phrases on an early window; score lift on a later embargo window."""
    if not observations:
        return {
            "train_article_count": 0,
            "test_article_count": 0,
            "train_cutoff_at": None,
            "baseline_forward_return_4w_train": None,
            "baseline_forward_return_4w_test": None,
            "phrases": [],
        }

    article_times = sorted({item.published_at for item in observations})
    cutoff_index = max(1, min(len(article_times) - 1, int(len(article_times) * train_fraction)))
    cutoff = article_times[cutoff_index - 1]
    train = [item for item in observations if item.published_at <= cutoff]
    test = [item for item in observations if item.published_at > cutoff]

    def baseline(rows: list[PhraseObservation]) -> float | None:
        by_article: dict[str, float] = {}
        for item in rows:
            if item.forward_return_4w is None:
                continue
            by_article[item.article_id] = float(item.forward_return_4w)
        return _mean(list(by_article.values()))

    train_baseline = baseline(train)
    test_baseline = baseline(test)
    train_stats = _rank_phrases(
        _phrase_stats(train, baseline_4w=train_baseline),
        min_train_count=min_train_count,
    )
    test_by_phrase = {row["phrase"]: row for row in _phrase_stats(test, baseline_4w=test_baseline)}

    combined: list[dict[str, Any]] = []
    for row in train_stats:
        test_row = test_by_phrase.get(row["phrase"])
        entry = dict(row)
        entry["train_lift_vs_baseline_4w"] = row.get("lift_vs_baseline_4w")
        entry["test_observation_count"] = (test_row or {}).get("observation_count", 0)
        entry["test_labeled_4w_count"] = (test_row or {}).get("labeled_4w_count", 0)
        entry["test_mean_forward_return_4w"] = (test_row or {}).get("mean_forward_return_4w")
        entry["test_lift_vs_baseline_4w"] = (test_row or {}).get("lift_vs_baseline_4w")
        entry["test_up_hit_rate_4w"] = (test_row or {}).get("up_hit_rate_4w")
        test_lift = entry.get("test_lift_vs_baseline_4w")
        train_lift = entry.get("train_lift_vs_baseline_4w")
        test_n = int(entry.get("test_labeled_4w_count") or 0)
        if (
            entry.get("status") == "promoted"
            and test_n >= max(2, min_train_count // 2)
            and test_lift is not None
            and train_lift is not None
            and float(test_lift) * float(train_lift) <= 0
        ):
            entry["status"] = "demoted"
            entry["status_reason"] = "test_sign_disagrees"
        elif entry.get("status") == "promoted" and test_n < max(2, min_train_count // 2):
            entry["status"] = "watch"
            entry["status_reason"] = "insufficient_test_labels"
        combined.append(entry)

    return {
        "train_article_count": len({item.article_id for item in train}),
        "test_article_count": len({item.article_id for item in test}),
        "train_cutoff_at": _iso(cutoff),
        "baseline_forward_return_4w_train": train_baseline,
        "baseline_forward_return_4w_test": test_baseline,
        "phrases": combined,
    }


def _merge_self_improve(
    previous_lexicon: dict[str, Any] | None,
    current_phrases: list[dict[str, Any]],
) -> dict[str, Any]:
    prev_by_phrase = {
        str(row.get("phrase")): row
        for row in (previous_lexicon or {}).get("phrases") or []
        if row.get("phrase")
    }
    generation = int((previous_lexicon or {}).get("lexicon_generation") or 0) + 1
    promoted: list[str] = []
    demoted: list[str] = []
    continued: list[str] = []
    newly_seen: list[str] = []
    merged: list[dict[str, Any]] = []

    for row in current_phrases:
        phrase = str(row["phrase"])
        prev = prev_by_phrase.get(phrase)
        entry = dict(row)
        if prev is None:
            entry["generations_seen"] = 1
            newly_seen.append(phrase)
        else:
            entry["generations_seen"] = int(prev.get("generations_seen") or 1) + 1
            prev_status = str(prev.get("status") or "watch")
            cur_status = str(entry.get("status") or "watch")
            if cur_status == "promoted" and prev_status != "promoted":
                promoted.append(phrase)
            elif cur_status == "demoted" and prev_status == "promoted":
                demoted.append(phrase)
            elif cur_status == prev_status == "promoted":
                continued.append(phrase)
        merged.append(entry)

    return {
        "lexicon_generation": generation,
        "promoted_phrases": promoted[:40],
        "demoted_phrases": demoted[:40],
        "continued_promoted_phrases": continued[:40],
        "new_phrases": newly_seen[:40],
        "phrases": merged,
    }


def _format_review_markdown(panel: dict[str, Any], lexicon: dict[str, Any]) -> str:
    lines = [
        "# News phrase ↔ trajectory panel (observe-only)",
        "",
        f"- Generated: `{panel.get('generated_at')}`",
        f"- Source pool: `{panel.get('source_pool')}`",
        f"- Mode: `{panel.get('mode')}`",
        f"- Cohort tickers: **{panel.get('cohort_ticker_count')}** "
        f"(with news: **{panel.get('tickers_with_news')}**)",
        f"- Articles walked: **{panel.get('article_count')}**",
        f"- Phrase observations: **{panel.get('observation_count')}**",
        f"- Train cutoff: `{lexicon.get('train_cutoff_at')}`",
        f"- Lexicon generation: **{lexicon.get('lexicon_generation')}**",
        "",
        "## Self-improve delta",
        "",
        f"- Newly promoted: {len(lexicon.get('promoted_phrases') or [])}",
        f"- Demoted: {len(lexicon.get('demoted_phrases') or [])}",
        f"- Continued promoted: {len(lexicon.get('continued_promoted_phrases') or [])}",
        "",
        "## Top promoted phrases",
        "",
    ]
    promoted = [row for row in lexicon.get("phrases") or [] if row.get("status") == "promoted"][:15]
    if not promoted:
        lines.append("_No phrases cleared the promote gate this run._")
    else:
        lines.append("| rank | phrase | lift 4w | test lift 4w | tickers | n |")
        lines.append("|---:|---|---:|---:|---:|---:|")
        for row in promoted:
            lines.append(
                f"| {row.get('rank')} | `{row.get('phrase')}` | "
                f"{row.get('train_lift_vs_baseline_4w')} | "
                f"{row.get('test_lift_vs_baseline_4w')} | "
                f"{row.get('ticker_count')} | {row.get('labeled_4w_count')} |"
            )

    # Thin-history aid: surface strongest train-lift watch phrases until test labels densify.
    watch = [
        row
        for row in lexicon.get("phrases") or []
        if row.get("status") == "watch" and row.get("train_lift_vs_baseline_4w") is not None
    ]
    watch = sorted(
        watch,
        key=lambda row: abs(float(row.get("train_lift_vs_baseline_4w") or 0.0)),
        reverse=True,
    )[:15]
    lines.extend(["", "## Top watch candidates (train lift; awaiting test labels)", ""])
    if not watch:
        lines.append("_No watch candidates with labeled train lift._")
    else:
        lines.append("| rank | phrase | train lift 4w | reason | tickers | n |")
        lines.append("|---:|---|---:|---|---:|---:|")
        for row in watch:
            lines.append(
                f"| {row.get('rank')} | `{row.get('phrase')}` | "
                f"{row.get('train_lift_vs_baseline_4w')} | "
                f"{row.get('status_reason') or 'watch'} | "
                f"{row.get('ticker_count')} | {row.get('labeled_4w_count')} |"
            )

    lines.extend(["", "## Coverage notes", ""])
    for note in panel.get("notes") or []:
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)


def run_news_phrase_trajectory(
    data_dir: Path,
    *,
    mode: str = "full",
    train_fraction: float = DEFAULT_TRAIN_FRACTION,
    min_train_count: int = DEFAULT_MIN_TRAIN_COUNT,
    max_phrases: int = DEFAULT_MAX_PHRASES,
    tickers: list[str] | None = None,
) -> dict[str, Any]:
    """Full or rolling offline pass over the buy∪boundary cohort."""
    if mode not in {"full", "rolling"}:
        raise ValueError("mode must be 'full' or 'rolling'")

    data_dir = Path(data_dir)
    cohort = select_buy_boundary_cohort(data_dir)
    if tickers:
        wanted = {ticker.strip() for ticker in tickers if ticker.strip()}
        cohort = [row for row in cohort if row["ticker"] in wanted]

    state_path = resolve_json_path(data_dir / STATE_FILENAME)
    previous_state = read_json(state_path) if state_path is not None else {}
    previous_lexicon_path = resolve_json_path(data_dir / LEXICON_FILENAME)
    previous_lexicon = (
        read_json(previous_lexicon_path) if previous_lexicon_path is not None else None
    )
    watermarks = {
        str(key): _parse_dt(str(value))
        for key, value in (previous_state.get("ticker_watermarks") or {}).items()
    }

    indexed = _snapshot_index(load_run_snapshots(data_dir))
    transitions_by_ticker = _load_transitions_by_ticker(data_dir)

    all_observations: list[PhraseObservation] = []
    per_ticker: list[dict[str, Any]] = []
    new_watermarks: dict[str, str] = {}
    articles_total = 0
    tickers_with_news = 0

    for member in cohort:
        ticker = member["ticker"]
        articles = load_news_manifest(data_dir, ticker)
        if articles:
            tickers_with_news += 1
        articles_total += len(articles)
        since = watermarks.get(ticker) if mode == "rolling" else None
        observations = build_observations_for_ticker(
            ticker=ticker,
            name=member.get("name"),
            articles=articles,
            indexed_snapshots=indexed,
            transitions=transitions_by_ticker.get(ticker) or [],
        )
        incremental = [row for row in observations if since is None or row.published_at > since]
        all_observations.extend(observations)

        dated_ok = [
            dt
            for dt in (_parse_dt(str(row.get("published_at") or "")) for row in articles)
            if dt is not None
        ]
        latest_article_at = max(dated_ok) if dated_ok else None
        if latest_article_at is not None:
            new_watermarks[ticker] = latest_article_at.isoformat()

        per_ticker.append(
            {
                "ticker": ticker,
                "name": member.get("name"),
                "cohort_tags": member.get("cohort_tags"),
                "signal": member.get("signal"),
                "article_count": len(articles),
                "observation_count": len(observations),
                "new_observation_count": len(incremental),
                "labeled_4w_observation_count": sum(
                    1 for row in observations if row.forward_return_4w is not None
                ),
                "latest_article_at": _iso(latest_article_at),
            }
        )

    lexicon_core = walk_forward_lexicon(
        all_observations,
        train_fraction=train_fraction,
        min_train_count=min_train_count,
    )
    improved = _merge_self_improve(previous_lexicon, lexicon_core["phrases"][: max_phrases * 3])
    improved_phrases = improved["phrases"][:max_phrases]
    improved["phrases"] = improved_phrases
    generated_at = datetime.now(UTC).isoformat()
    improved.update(
        {
            "schema_version": SCHEMA_VERSION,
            "scope": "news_phrase_lexicon",
            "observe_only": True,
            "source_pool": SOURCE_POOL,
            "generated_at": generated_at,
            "train_article_count": lexicon_core["train_article_count"],
            "test_article_count": lexicon_core["test_article_count"],
            "train_cutoff_at": lexicon_core["train_cutoff_at"],
            "baseline_forward_return_4w_train": lexicon_core["baseline_forward_return_4w_train"],
            "baseline_forward_return_4w_test": lexicon_core["baseline_forward_return_4w_test"],
            "mode": mode,
        }
    )

    notes = [
        "Observe-only: does not modify screen weights or paper knobs.",
        "Forward returns use archive snapshots (same family as trajectory evidence).",
        "Promotion requires train lift and non-contradictory test lift when labels exist.",
        "Memo-grade / non-cohort news remains isolated until a later gated pass.",
    ]
    if len(indexed) < max(FORWARD_HORIZONS_WEEKS) + 1:
        notes.append(
            f"Archive history is thin ({len(indexed)} snapshots); "
            "12w labels will be sparse until history densifies."
        )

    panel = {
        "schema_version": SCHEMA_VERSION,
        "scope": "news_phrase_trajectory",
        "observe_only": True,
        "source_pool": SOURCE_POOL,
        "mode": mode,
        "generated_at": generated_at,
        "cohort_ticker_count": len(cohort),
        "tickers_with_news": tickers_with_news,
        "article_count": articles_total,
        "observation_count": len(all_observations),
        "archive_snapshot_count": len(indexed),
        "train_cutoff_at": lexicon_core["train_cutoff_at"],
        "lexicon_generation": improved["lexicon_generation"],
        "promoted_count": sum(1 for row in improved_phrases if row.get("status") == "promoted"),
        "demoted_count": sum(1 for row in improved_phrases if row.get("status") == "demoted"),
        "watch_count": sum(1 for row in improved_phrases if row.get("status") == "watch"),
        "top_promoted_phrases": [
            row for row in improved_phrases if row.get("status") == "promoted"
        ][:20],
        "per_ticker": per_ticker,
        "notes": notes,
    }
    state = {
        "schema_version": SCHEMA_VERSION,
        "scope": "news_phrase_trajectory_state",
        "updated_at": generated_at,
        "mode_last_run": mode,
        "lexicon_generation": improved["lexicon_generation"],
        "ticker_watermarks": new_watermarks,
    }

    write_json(data_dir / PANEL_FILENAME, panel, compact=False, compress=False)
    write_json(data_dir / LEXICON_FILENAME, improved, compact=False, compress=False)
    write_json(data_dir / STATE_FILENAME, state, compact=False, compress=False)
    (data_dir / REVIEW_MD_FILENAME).write_text(
        _format_review_markdown(panel, improved),
        encoding="utf-8",
    )

    return {
        "panel": panel,
        "lexicon": improved,
        "state": state,
        "paths": {
            "panel": str(data_dir / PANEL_FILENAME),
            "lexicon": str(data_dir / LEXICON_FILENAME),
            "state": str(data_dir / STATE_FILENAME),
            "review_md": str(data_dir / REVIEW_MD_FILENAME),
        },
    }


__all__ = [
    "LEXICON_FILENAME",
    "PANEL_FILENAME",
    "REVIEW_MD_FILENAME",
    "STATE_FILENAME",
    "extract_phrases",
    "run_news_phrase_trajectory",
    "select_buy_boundary_cohort",
    "walk_forward_lexicon",
]
