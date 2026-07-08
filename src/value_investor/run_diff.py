"""Compare screening runs to highlight signal changes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from value_investor.signals import SIGNAL_ORDER


@dataclass
class RunDiff:
    previous_run_at: str | None
    new_strong_buys: list[str]
    lost_strong_buys: list[str]
    upgrades: list[str]
    downgrades: list[str]
    unchanged_top_signals: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "previous_run_at": self.previous_run_at,
            "new_strong_buys": self.new_strong_buys,
            "lost_strong_buys": self.lost_strong_buys,
            "upgrades": self.upgrades,
            "downgrades": self.downgrades,
            "unchanged_top_signals": self.unchanged_top_signals,
        }

    def has_changes(self) -> bool:
        return bool(
            self.new_strong_buys
            or self.lost_strong_buys
            or self.upgrades
            or self.downgrades
        )


def _signal_rank(signal: str) -> int:
    from value_investor.signals import Signal

    try:
        return SIGNAL_ORDER[Signal(signal)]
    except ValueError:
        return 0


def compute_run_diff(previous: pd.DataFrame, current: pd.DataFrame) -> RunDiff:
    """Diff signal changes between two screening runs."""
    prev = previous.set_index("ticker") if "ticker" in previous.columns else previous
    curr = current.set_index("ticker") if "ticker" in current.columns else current

    common = prev.index.intersection(curr.index)
    new_strong_buys: list[str] = []
    lost_strong_buys: list[str] = []
    upgrades: list[str] = []
    downgrades: list[str] = []
    unchanged = 0

    for ticker in common:
        prev_signal = str(prev.loc[ticker].get("signal", "hold"))
        curr_signal = str(curr.loc[ticker].get("signal", "hold"))
        name = str(curr.loc[ticker].get("name", ticker))

        if prev_signal == curr_signal:
            unchanged += 1
            continue

        prev_rank = _signal_rank(prev_signal)
        curr_rank = _signal_rank(curr_signal)
        label = f"{name} ({ticker}): {prev_signal} → {curr_signal}"

        if curr_signal == "strong_buy" and prev_signal != "strong_buy":
            new_strong_buys.append(label)
        if prev_signal == "strong_buy" and curr_signal != "strong_buy":
            lost_strong_buys.append(label)

        if curr_rank > prev_rank:
            upgrades.append(label)
        elif curr_rank < prev_rank:
            downgrades.append(label)

    previous_run_at = None
    if "run_at" in previous.columns and not previous.empty:
        previous_run_at = str(previous["run_at"].iloc[0])

    return RunDiff(
        previous_run_at=previous_run_at,
        new_strong_buys=new_strong_buys,
        lost_strong_buys=lost_strong_buys,
        upgrades=upgrades,
        downgrades=downgrades,
        unchanged_top_signals=unchanged,
    )


def format_run_diff_text(diff: RunDiff) -> str:
    if not diff.has_changes():
        return "No signal changes since the previous run."

    lines = ["Changes since previous run:"]
    if diff.previous_run_at:
        lines[0] += f" ({diff.previous_run_at})"

    sections = [
        ("New strong buys", diff.new_strong_buys),
        ("Lost strong buys", diff.lost_strong_buys),
        ("Upgrades", [u for u in diff.upgrades if u not in diff.new_strong_buys]),
        ("Downgrades", [d for d in diff.downgrades if d not in diff.lost_strong_buys]),
    ]
    for title, items in sections:
        if items:
            lines.append(f"{title}: " + "; ".join(items[:5]))
            if len(items) > 5:
                lines.append(f"  …and {len(items) - 5} more")

    lines.append(f"Unchanged signals: {diff.unchanged_top_signals} companies")
    return "\n".join(lines)
