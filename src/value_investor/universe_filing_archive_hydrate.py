"""Fail-open pack hydrate for the universe filing archive lane (L499).

Archive packs are a **best-effort accelerator**. On activate/hydrate:

- Use the pack if present and readable
- On miss / hole / error → fall through to live deepen
- Never block the active regime on pack holes

Writers live in ``universe_filing_archive_writer``; this module is path layout +
fail-open hydrate lookup only. Missing packs return ``status=miss`` with
``fail_open=True``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from value_investor.storage import read_json

SCHEMA_VERSION = 1
DEFAULT_COLD_ROOT = Path("docs/data/archive/universe_filings")

HydrateStatus = Literal["hit", "miss", "unavailable", "error"]


@dataclass(frozen=True)
class HydrateResult:
    """Outcome of a fail-open pack hydrate attempt."""

    status: HydrateStatus
    market_id: str
    ticker: str
    fail_open: bool = True
    reason: str = ""
    pack_path: str | None = None
    object_count: int = 0
    objects: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": self.status,
            "market_id": self.market_id,
            "ticker": self.ticker,
            "fail_open": self.fail_open,
            "reason": self.reason,
            "pack_path": self.pack_path,
            "object_count": self.object_count,
            "objects": list(self.objects),
            "continue_live_deepen": True,  # always — archive never blocks
        }


def cold_market_dir(market_id: str, *, cold_root: Path = DEFAULT_COLD_ROOT) -> Path:
    mid = str(market_id or "").strip() or "_unknown"
    return Path(cold_root) / "markets" / mid


def cold_ticker_dir(
    market_id: str,
    ticker: str,
    *,
    cold_root: Path = DEFAULT_COLD_ROOT,
) -> Path:
    tick = str(ticker or "").strip().upper() or "_UNKNOWN"
    return cold_market_dir(market_id, cold_root=cold_root) / "tickers" / tick


def pack_index_path(
    market_id: str,
    ticker: str,
    *,
    cold_root: Path = DEFAULT_COLD_ROOT,
) -> Path:
    """Per-ticker pack index (metadata for assemble/hydrate)."""
    return cold_ticker_dir(market_id, ticker, cold_root=cold_root) / "pack_index.json"


def raw_object_path(
    market_id: str,
    ticker: str,
    object_id: str,
    *,
    cold_root: Path = DEFAULT_COLD_ROOT,
) -> Path:
    oid = str(object_id or "").strip() or "object"
    return cold_ticker_dir(market_id, ticker, cold_root=cold_root) / "raw" / oid


def normalized_zstd_path(
    market_id: str,
    ticker: str,
    object_id: str,
    *,
    cold_root: Path = DEFAULT_COLD_ROOT,
) -> Path:
    oid = str(object_id or "").strip() or "object"
    return cold_ticker_dir(market_id, ticker, cold_root=cold_root) / "normalized" / f"{oid}.txt.zst"


def _safe_read_index(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def try_hydrate_pack(
    market_id: str,
    ticker: str,
    *,
    cold_root: Path = DEFAULT_COLD_ROOT,
) -> HydrateResult:
    """Attempt pack hydrate; always fail-open so live deepen can continue.

    Does **not** write research dirs, rememo, or deepen. Callers copy objects
    into the live research path only after a ``hit`` (future work).
    """
    mid = str(market_id or "").strip()
    tick = str(ticker or "").strip().upper()
    if not mid or not tick:
        return HydrateResult(
            status="unavailable",
            market_id=mid,
            ticker=tick,
            reason="market_id and ticker are required",
        )

    index_path = pack_index_path(mid, tick, cold_root=Path(cold_root))
    if not index_path.exists():
        return HydrateResult(
            status="miss",
            market_id=mid,
            ticker=tick,
            reason="no_pack_index",
            pack_path=str(index_path),
        )

    payload = _safe_read_index(index_path)
    if payload is None:
        return HydrateResult(
            status="error",
            market_id=mid,
            ticker=tick,
            reason="pack_index_unreadable",
            pack_path=str(index_path),
        )

    objects_raw = payload.get("objects") or payload.get("filings") or []
    if not isinstance(objects_raw, list):
        objects_raw = []
    objects: list[dict[str, Any]] = [o for o in objects_raw if isinstance(o, dict)]
    if not objects:
        return HydrateResult(
            status="miss",
            market_id=mid,
            ticker=tick,
            reason="pack_index_empty",
            pack_path=str(index_path),
            object_count=0,
        )

    return HydrateResult(
        status="hit",
        market_id=mid,
        ticker=tick,
        reason="pack_present",
        pack_path=str(index_path),
        object_count=len(objects),
        objects=tuple(objects),
    )


def hydrate_or_continue_live_deepen(
    market_id: str,
    ticker: str,
    *,
    cold_root: Path = DEFAULT_COLD_ROOT,
) -> dict[str, Any]:
    """Convenience wrapper: hydrate result + explicit live-deepen continue flag."""
    result = try_hydrate_pack(market_id, ticker, cold_root=cold_root)
    payload = result.to_dict()
    # Fail-open contract: hit accelerates; miss/error/unavailable never blocks.
    payload["continue_live_deepen"] = True
    payload["use_pack"] = result.status == "hit"
    return payload


__all__ = [
    "DEFAULT_COLD_ROOT",
    "HydrateResult",
    "HydrateStatus",
    "SCHEMA_VERSION",
    "cold_market_dir",
    "cold_ticker_dir",
    "hydrate_or_continue_live_deepen",
    "normalized_zstd_path",
    "pack_index_path",
    "raw_object_path",
    "try_hydrate_pack",
]
