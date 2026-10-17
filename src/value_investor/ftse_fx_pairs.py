"""SEK and HKD quotes from the existing macro FX fetch.

The pinned 16 Oct macro snapshot has no SEK or HKD marker. This asks the same
Yahoo close fetch those markers use. A positive close is stored in that marker
shape. A missing close is not stored, and no pound cap is recalculated.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from value_investor.storage import write_json

SEK_HKD_PAIRS = (
    ("sek_usd", "SEKUSD=X"),
    ("hkd_usd", "HKDUSD=X"),
)
SNAPSHOT_NAME = "sek-hkd.json"
CloseFetcher = Callable[[str], dict[str, Any] | None]


def sek_hkd_markers(fetcher: CloseFetcher) -> tuple[dict[str, Any], list[str]]:
    """Return markers the fetcher actually priced, and symbols it did not."""

    markers: dict[str, Any] = {}
    missing: list[str] = []
    for key, symbol in SEK_HKD_PAIRS:
        row = fetcher(symbol)
        value = row.get("value") if isinstance(row, dict) else None
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            missing.append(symbol)
            continue
        marker: dict[str, Any] = {"symbol": symbol, "value": value}
        as_of = row.get("as_of") if isinstance(row, dict) else None
        if isinstance(as_of, str) and as_of.strip():
            marker["as_of"] = as_of
        markers[key] = marker
    return markers, missing


def write_sek_hkd_snapshot(root: Path, markers: dict[str, Any]) -> Path | None:
    """Write the macro marker file. Does not replace the pinned snapshot."""

    if not markers:
        return None
    payload = {
        "note": (
            "SEK and HKD closes from the existing Yahoo FX fetch. "
            "Do not use these rates to fill a pound cap the pinned snapshot does not price."
        ),
        "domains": {"fx": {"domain": "fx", "markers": markers}},
    }
    return write_json(
        Path(root) / "docs/data/library/macro" / SNAPSHOT_NAME,
        payload,
        compact=False,
        compress=False,
    )


def fetch_sek_hkd(
    root: Path, *, fetcher: CloseFetcher | None = None
) -> tuple[Path | None, list[str]]:
    if fetcher is None:
        from value_investor.macro_context import _latest_close

        fetcher = _latest_close
    markers, missing = sek_hkd_markers(fetcher)
    return write_sek_hkd_snapshot(root, markers), missing
