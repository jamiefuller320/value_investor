"""Settle explicit splits, cash bids, and delistings on a paper fund (L562).

The daily paper pass applies a committed event feed before rebalance. A split
changes the share count and average cost. A cash bid or a delisting with a
cash amount becomes cash on the event date, through the normal sell path.
A terminal event with no cash amount is flagged unsettled and the position
stays open. Nothing here infers a split from a price jump, and nothing
rewrites the equity curve.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from value_investor.paper_fund import PaperFund

EVENTS_FILENAME = "corporate_actions.json"
DEFAULT_EVENTS_PATH = Path("docs/data/corporate_actions.json")
FINDING_TITLE = "Paper holding has an unsettled terminal event"
TERMINAL_TYPES = frozenset({"cash_bid", "delisting"})


def _parse_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def load_corporate_actions(*paths: Path) -> list[dict[str, Any]]:
    """Read event objects from the first paths that exist. Later files do not override."""
    events: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in paths:
        if not path or not Path(path).exists():
            continue
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rows = payload.get("events") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict) or not row.get("id"):
                continue
            event_id = str(row["id"])
            if event_id in seen:
                continue
            seen.add(event_id)
            events.append(dict(row))
    return events


def events_from_split_ratios(ticker: str, ratios: dict[date, float]) -> list[dict[str, Any]]:
    """Turn an explicit split-ratio series into feed events. A ratio of 1 is ignored.

    This does not look at prices. Callers pass ratios they already trust
    (a committed feed, or a Yahoo split series they have chosen to accept).
    """
    events: list[dict[str, Any]] = []
    for day in sorted(ratios):
        ratio = float(ratios[day])
        if ratio <= 0 or abs(ratio - 1.0) < 1e-9:
            continue
        events.append(
            {
                "id": f"{ticker}:{day.isoformat()}:split",
                "ticker": ticker,
                "type": "split",
                "effective_at": datetime(day.year, day.month, day.day, 8, tzinfo=UTC).isoformat(),
                "ratio": ratio,
            }
        )
    return events


def _remember_unsettled(fund: PaperFund, row: dict[str, Any]) -> None:
    event_id = str(row["id"])
    fund.unsettled_corporate_actions = [
        item for item in fund.unsettled_corporate_actions if str(item.get("id")) != event_id
    ]
    fund.unsettled_corporate_actions.append(row)


def _clear_unsettled(fund: PaperFund, event_id: str) -> None:
    fund.unsettled_corporate_actions = [
        item for item in fund.unsettled_corporate_actions if str(item.get("id")) != event_id
    ]


def apply_corporate_actions(
    fund: PaperFund,
    events: list[dict[str, Any]],
    *,
    as_of: datetime | str | None = None,
) -> dict[str, Any]:
    """Apply events idempotently. Returns what changed. Does not append equity marks."""
    moment = _parse_dt(as_of) if not isinstance(as_of, datetime) else as_of
    if moment is not None and moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    curve_before = list(fund.equity_curve)
    settled_before = len(fund.settled_corporate_actions)
    applied: list[str] = []
    unsettled: list[str] = []
    skipped: list[str] = []
    settled = set(fund.settled_corporate_actions)

    for event in events:
        event_id = str(event.get("id") or "")
        if not event_id or event_id in settled:
            continue
        effective = _parse_dt(event.get("effective_at"))
        if effective is None or (moment is not None and effective > moment):
            skipped.append(event_id)
            continue
        ticker = str(event.get("ticker") or "")
        kind = str(event.get("type") or "")
        position = fund.holdings.get(ticker)
        if position is None or position.shares <= 0:
            fund.settled_corporate_actions.append(event_id)
            settled.add(event_id)
            skipped.append(event_id)
            continue
        opened = _parse_dt(position.opened_at)
        if opened is not None and opened > effective:
            fund.settled_corporate_actions.append(event_id)
            settled.add(event_id)
            skipped.append(event_id)
            continue
        if kind == "split":
            ratio = float(event.get("ratio") or 0)
            if ratio <= 0:
                skipped.append(event_id)
                continue
            position.shares *= ratio
            position.avg_cost = position.avg_cost / ratio
            fund.settled_corporate_actions.append(event_id)
            settled.add(event_id)
            _clear_unsettled(fund, event_id)
            applied.append(event_id)
            continue
        if kind in TERMINAL_TYPES:
            cash = event.get("cash_per_share")
            if not isinstance(cash, (int, float)) or float(cash) <= 0:
                _remember_unsettled(
                    fund,
                    {
                        "id": event_id,
                        "ticker": ticker,
                        "type": kind,
                        "effective_at": event.get("effective_at"),
                        "reason": "No cash amount; position left open.",
                    },
                )
                unsettled.append(event_id)
                continue
            fund.sell(
                ticker=ticker,
                price=float(cash),
                sizing_mode="shares",
                amount=position.shares,
                note=f"{kind} {event_id}",
                acted_at=effective.isoformat(),
            )
            fund.settled_corporate_actions.append(event_id)
            settled.add(event_id)
            _clear_unsettled(fund, event_id)
            applied.append(event_id)
            continue
        skipped.append(event_id)

    if fund.equity_curve != curve_before:
        fund.equity_curve = curve_before
    return {
        "applied": applied,
        "unsettled": unsettled,
        "skipped": skipped,
        "changed": bool(applied or unsettled)
        or len(fund.settled_corporate_actions) != settled_before,
    }


def settle_fund_corporate_actions(
    fund: PaperFund,
    output_dir: Path,
    *,
    as_of: datetime | str | None = None,
    events_path: Path | None = None,
) -> dict[str, Any]:
    """Apply the track feed and the committed feed. Missing files are a no-op."""
    paths = [Path(output_dir) / EVENTS_FILENAME]
    if events_path is not None:
        paths.append(Path(events_path))
    else:
        paths.append(DEFAULT_EVENTS_PATH)
    return apply_corporate_actions(fund, load_corporate_actions(*paths), as_of=as_of)


def finding_for_funds(funds: list[tuple[str, PaperFund]]) -> dict[str, Any] | None:
    rows = []
    for track_id, fund in funds:
        for item in fund.unsettled_corporate_actions:
            rows.append(f"{track_id} {item.get('ticker')} ({item.get('type')})")
    if not rows:
        return None
    return {
        "severity": "warn",
        "category": "paper",
        "title": FINDING_TITLE,
        "summary": (
            "A split, cash bid, or delisting has no cash amount, so the paper position "
            "is still open. It was not zeroed. "
            + "; ".join(rows)
            + ". Add cash_per_share to the corporate-actions feed. "
            "See docs/ops/corporate-actions.md."
        ),
        "auto_fixable": False,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Settle explicit paper-ledger corporate actions")
    parser.add_argument("--fund", type=Path, required=True)
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS_PATH)
    parser.add_argument("--as-of", default=None)
    args = parser.parse_args(argv)
    payload = json.loads(args.fund.read_text(encoding="utf-8"))
    fund = PaperFund.from_dict(payload)
    result = settle_fund_corporate_actions(
        fund, args.fund.parent, as_of=args.as_of, events_path=args.events
    )
    args.fund.write_text(json.dumps(fund.to_dict(), indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
