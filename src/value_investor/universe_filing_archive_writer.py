"""Thin quiet-window cold-store writers for the universe filing archive lane (L499).

Bounded apply path under ``archive_lane_gate``:

- Tiny ``max_units`` / tickers / bodies / HTTP fetch caps (cannot starve P1/P2)
- Separate archive budget IDs (never ``critical_path:*``)
- Writes only under ``docs/data/archive/universe_filings`` (not live research)
- No memo / scoring / eng-spray (N181); not a fourth equal sprint (N180)

Network discovery is injectable for tests. Production uses primary filing
discover + ``fetch_filing_body`` with hard per-run fetch budgets.
"""

from __future__ import annotations

import csv
import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.storage import write_json
from value_investor.universe_filing_archive_hydrate import (
    DEFAULT_COLD_ROOT,
    normalized_zstd_path,
    pack_index_path,
    raw_object_path,
    try_hydrate_pack,
)
from value_investor.universe_filing_archive_isolation import (
    ARCHIVE_LANE_BUDGET_ID,
    CRITICAL_PATH_BUDGET_ID,
    archive_budget_id,
    budgets_share_quota,
)

SCHEMA_VERSION = 1

# Hard caps for the quiet-window pilot — keep shared runners/sources free.
DEFAULT_APPLY_MAX_UNITS = 2
DEFAULT_MAX_TICKERS_PER_UNIT = 2
DEFAULT_MAX_BODIES_PER_TICKER = 1
DEFAULT_MAX_DISCOVER_ITEMS = 3
DEFAULT_MAX_HTTP_FETCHES = 8
DEFAULT_LIBRARY_ROOT = Path("docs/data/library")

DiscoverFn = Callable[[str, str, str], list[dict[str, Any]]]
BodyFetchFn = Callable[[str, str], str | None]


@dataclass
class ArchiveFetchBudget:
    """Per-run archive-lane HTTP budget. Never shares critical-path quota."""

    max_fetches: int = DEFAULT_MAX_HTTP_FETCHES
    fetches: int = 0
    by_budget: dict[str, int] = field(default_factory=dict)
    skipped_budget_exhausted: int = 0

    def can_fetch(self) -> bool:
        return self.fetches < int(self.max_fetches)

    def record(self, source: str) -> str:
        bid = archive_budget_id(source)
        if budgets_share_quota(bid, critical_budget_probe()):
            raise RuntimeError(f"archive writer refused critical-path budget: {bid}")
        if not bid.startswith(f"{ARCHIVE_LANE_BUDGET_ID}:"):
            raise RuntimeError(f"archive writer requires archive budget id, got {bid}")
        self.fetches += 1
        self.by_budget[bid] = int(self.by_budget.get(bid) or 0) + 1
        return bid

    def try_record(self, source: str) -> str | None:
        if not self.can_fetch():
            self.skipped_budget_exhausted += 1
            return None
        return self.record(source)

    def snapshot(self) -> dict[str, Any]:
        used = sorted(self.by_budget)
        shared = any(budgets_share_quota(bid, f"{CRITICAL_PATH_BUDGET_ID}:probe") for bid in used)
        return {
            "lane_budget": ARCHIVE_LANE_BUDGET_ID,
            "source_budgets_used": used,
            "fetches_by_budget": dict(self.by_budget),
            "http_fetches": self.fetches,
            "max_http_fetches": int(self.max_fetches),
            "skipped_budget_exhausted": self.skipped_budget_exhausted,
            "shared_critical_path": False if not shared else True,
            "preemptible": True,
            "fourth_equal_sprint_stream": False,
            "isolation_ok": (not shared)
            and all(b.startswith(f"{ARCHIVE_LANE_BUDGET_ID}:") for b in used),
        }


def critical_budget_probe() -> str:
    return f"{CRITICAL_PATH_BUDGET_ID}:probe"


def _safe_object_id(source: str, url: str, title: str = "") -> str:
    raw = f"{source}|{url}|{title}".encode()
    digest = hashlib.sha256(raw).hexdigest()[:16]
    src = re.sub(r"[^a-z0-9]+", "_", str(source or "src").lower()).strip("_") or "src"
    return f"{src}_{digest}"


def _compress_normalized(text: str) -> tuple[bytes, str]:
    """Return (bytes, codec). Prefer zstd; fall back to utf-8 for thin pilot."""
    data = text.encode("utf-8")
    try:
        import zstandard as zstd  # type: ignore[import-not-found]

        return zstd.ZstdCompressor(level=3).compress(data), "zstd"
    except Exception:  # noqa: BLE001 — optional dep / compressor failure
        return data, "utf-8"


def select_pilot_tickers(
    market_id: str,
    *,
    max_tickers: int = DEFAULT_MAX_TICKERS_PER_UNIT,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    universe_csv: Path | None = None,
) -> list[dict[str, str]]:
    """Pick a tiny stable ticker roster for one market (library universe CSV)."""
    mid = str(market_id or "").strip()
    cap = max(0, int(max_tickers))
    if not mid or cap <= 0:
        return []
    path = (
        Path(universe_csv)
        if universe_csv is not None
        else (Path(library_root) / "markets" / mid / "screen" / "latest_universe.csv")
    )
    if not path.exists():
        return []
    out: list[dict[str, str]] = []
    try:
        with path.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                tick = str(row.get("ticker") or "").strip().upper()
                if not tick:
                    continue
                name = str(row.get("name") or row.get("company_name") or tick).strip()
                out.append({"ticker": tick, "name": name, "market_id": mid})
                if len(out) >= cap:
                    break
    except OSError:
        return []
    return out


def _default_discover(market_id: str, ticker: str, company_name: str) -> list[dict[str, Any]]:
    """Primary-source discovery only — no news / deepen fan-out."""
    from value_investor.research.filings import (
        fetch_filings_esef_direct,
        fetch_filings_ir_allowlist,
        fetch_filings_sec_edgar,
        resolve_filings_regime,
    )

    regime = resolve_filings_regime(market_id, ticker)
    rows: list[dict[str, Any]] = []
    if regime == "sec_edgar":
        rows.extend(
            fetch_filings_sec_edgar(
                ticker=ticker,
                max_items=DEFAULT_MAX_DISCOVER_ITEMS,
                lookback_days=400,
                include_current_reports=False,
            )
            or []
        )
    elif regime == "euro_filings":
        rows.extend(
            fetch_filings_esef_direct(
                company_name=company_name or ticker,
                ticker=ticker,
                max_items=DEFAULT_MAX_DISCOVER_ITEMS,
                lookback_days=400,
            )
            or []
        )
        rows.extend(fetch_filings_ir_allowlist(ticker) or [])
    elif regime == "uk_rns":
        rows.extend(fetch_filings_ir_allowlist(ticker) or [])
    else:
        # Other markets: IR allowlist only for the thin pilot.
        rows.extend(fetch_filings_ir_allowlist(ticker) or [])

    # Dedup by URL, keep first N.
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        source = str(row.get("source") or "").strip().lower() or _infer_source(url, regime)
        out.append({**row, "source": source, "url": url})
        if len(out) >= DEFAULT_MAX_DISCOVER_ITEMS:
            break
    return out


def _infer_source(url: str, regime: str) -> str:
    u = url.lower()
    if "sec.gov" in u:
        return "sec"
    if "companieshouse" in u or "company-information.service.gov.uk" in u:
        return "companies_house"
    if "filings.xbrl.org" in u or "esef" in u:
        return "esef"
    if regime == "sec_edgar":
        return "sec"
    if regime == "euro_filings":
        return "esef"
    return "ir_pdf"


def _default_body_fetch(url: str, source: str) -> str | None:
    from value_investor.research.filings import fetch_filing_body

    _ = source
    return fetch_filing_body(url)


def write_cold_objects(
    *,
    market_id: str,
    ticker: str,
    unit_id: str,
    filings: list[dict[str, Any]],
    bodies: dict[str, str],
    cold_root: Path = DEFAULT_COLD_ROOT,
    budget_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Persist pack_index + raw + normalized under the cold root (no live research)."""
    mid = str(market_id or "").strip()
    tick = str(ticker or "").strip().upper()
    objects: list[dict[str, Any]] = []
    for row in filings:
        url = str(row.get("url") or "").strip()
        if not url or url not in bodies:
            continue
        source = str(row.get("source") or "ir_pdf").strip().lower()
        oid = _safe_object_id(source, url, str(row.get("title") or ""))
        text = bodies[url]
        raw_path = raw_object_path(mid, tick, oid, cold_root=cold_root)
        norm_path = normalized_zstd_path(mid, tick, oid, cold_root=cold_root)
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        norm_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(text.encode("utf-8"))
        compressed, codec = _compress_normalized(text)
        norm_path.write_bytes(compressed)
        objects.append(
            {
                "id": oid,
                "source": source,
                "url": url,
                "title": str(row.get("title") or "")[:200] or None,
                "period": row.get("period"),
                "filed_at": row.get("filed_at") or row.get("date"),
                "raw_path": str(raw_path),
                "normalized_path": str(norm_path),
                "normalized_codec": codec,
                "char_count": len(text),
            }
        )

    index = {
        "schema_version": SCHEMA_VERSION,
        "market_id": mid,
        "ticker": tick,
        "unit_id": unit_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "lane": ARCHIVE_LANE_BUDGET_ID,
        "budget_ids": list(budget_ids or []),
        "object_count": len(objects),
        "objects": objects,
    }
    idx_path = pack_index_path(mid, tick, cold_root=cold_root)
    idx_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(idx_path, index)
    return index


def assemble_archive_pack_units(
    plan: dict[str, Any],
    *,
    cold_root: Path = DEFAULT_COLD_ROOT,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    max_tickers_per_unit: int = DEFAULT_MAX_TICKERS_PER_UNIT,
    max_bodies_per_ticker: int = DEFAULT_MAX_BODIES_PER_TICKER,
    max_http_fetches: int = DEFAULT_MAX_HTTP_FETCHES,
    discover_fn: DiscoverFn | None = None,
    body_fetch_fn: BodyFetchFn | None = None,
) -> dict[str, Any]:
    """Fetch+write cold packs for planned week×market units (bounded)."""
    units = [u for u in (plan.get("units") or []) if isinstance(u, dict)]
    budget = ArchiveFetchBudget(max_fetches=int(max_http_fetches))
    discover = discover_fn or _default_discover
    body_fetch = body_fetch_fn or _default_body_fetch

    attempted = 0
    completed = 0
    objects_written = 0
    tickers_touched = 0
    hydrate_hits = 0
    unit_results: list[dict[str, Any]] = []
    errors: list[str] = []
    by_source: dict[str, dict[str, int]] = {}

    for unit in units:
        if not budget.can_fetch():
            unit_results.append(
                {
                    "unit_id": unit.get("unit_id"),
                    "status": "skipped_budget",
                    "market_id": unit.get("market_id"),
                }
            )
            continue
        attempted += 1
        mid = str(unit.get("market_id") or "").strip()
        unit_id = str(unit.get("unit_id") or f"{mid}")
        tickers = select_pilot_tickers(
            mid,
            max_tickers=max_tickers_per_unit,
            library_root=library_root,
        )
        if not tickers:
            unit_results.append(
                {
                    "unit_id": unit_id,
                    "status": "skipped_no_tickers",
                    "market_id": mid,
                }
            )
            continue

        unit_objects = 0
        for row in tickers:
            if not budget.can_fetch():
                break
            tick = row["ticker"]
            name = row.get("name") or tick
            tickers_touched += 1
            try:
                filings = discover(mid, tick, name)
            except Exception as exc:  # noqa: BLE001 — fail-open unit
                errors.append(f"discover {mid}/{tick}: {exc}")
                filings = []

            # Count discovery as using archive budget (network).
            # Attribute to primary source family for the market.
            disc_source = _regime_budget_source(mid, tick)
            if filings and budget.try_record(disc_source) is None:
                break

            bodies: dict[str, str] = {}
            budget_ids: list[str] = []
            for filing in filings[: max(0, int(max_bodies_per_ticker))]:
                url = str(filing.get("url") or "").strip()
                source = str(filing.get("source") or disc_source).strip().lower()
                bid = budget.try_record(source)
                if bid is None:
                    break
                budget_ids.append(bid)
                try:
                    text = body_fetch(url, source)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"body {mid}/{tick}: {exc}")
                    text = None
                if text and len(text.strip()) >= 80:
                    bodies[url] = text
                    src_bucket = by_source.setdefault(source, {"fetches": 0, "bodies": 0})
                    src_bucket["fetches"] += 1
                    src_bucket["bodies"] += 1

            if not bodies:
                unit_results.append(
                    {
                        "unit_id": unit_id,
                        "status": "no_bodies",
                        "market_id": mid,
                        "ticker": tick,
                    }
                )
                continue

            index = write_cold_objects(
                market_id=mid,
                ticker=tick,
                unit_id=unit_id,
                filings=filings,
                bodies=bodies,
                cold_root=cold_root,
                budget_ids=budget_ids,
            )
            unit_objects += int(index.get("object_count") or 0)
            objects_written += int(index.get("object_count") or 0)
            hit = try_hydrate_pack(mid, tick, cold_root=cold_root)
            if hit.status == "hit":
                hydrate_hits += 1

        if unit_objects > 0:
            completed += 1
            unit_results.append(
                {
                    "unit_id": unit_id,
                    "status": "completed",
                    "market_id": mid,
                    "objects": unit_objects,
                }
            )
        elif not any(r.get("unit_id") == unit_id for r in unit_results):
            unit_results.append(
                {
                    "unit_id": unit_id,
                    "status": "empty",
                    "market_id": mid,
                }
            )

    isolation = budget.snapshot()
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "apply",
        "units_planned": int(plan.get("unit_count") or len(units)),
        "units_attempted": attempted,
        "units_completed": completed,
        "tickers_touched": tickers_touched,
        "objects_written": objects_written,
        "hydrate_hits": hydrate_hits,
        "by_source": by_source,
        "unit_results": unit_results[:40],
        "errors": errors,
        "capacity_isolation": isolation,
        "cold_root": str(cold_root),
        "caps": {
            "max_tickers_per_unit": int(max_tickers_per_unit),
            "max_bodies_per_ticker": int(max_bodies_per_ticker),
            "max_http_fetches": int(max_http_fetches),
            "max_discover_items": DEFAULT_MAX_DISCOVER_ITEMS,
            "default_apply_max_units": DEFAULT_APPLY_MAX_UNITS,
        },
        "fourth_equal_sprint_stream": False,
        "eng_spray": False,
        "note": (
            "Thin quiet cold-store assemble — archive budgets only; "
            "fail-open hydrate; no live deepen/memo (N180/N181)."
        ),
    }


def _regime_budget_source(market_id: str, ticker: str) -> str:
    from value_investor.research.filings import resolve_filings_regime

    regime = resolve_filings_regime(market_id, ticker)
    if regime == "sec_edgar":
        return "sec"
    if regime == "euro_filings":
        return "esef"
    if regime == "uk_rns":
        return "ir_pdf"
    return "ir_pdf"


__all__ = [
    "DEFAULT_APPLY_MAX_UNITS",
    "DEFAULT_LIBRARY_ROOT",
    "DEFAULT_MAX_BODIES_PER_TICKER",
    "DEFAULT_MAX_DISCOVER_ITEMS",
    "DEFAULT_MAX_HTTP_FETCHES",
    "DEFAULT_MAX_TICKERS_PER_UNIT",
    "ArchiveFetchBudget",
    "SCHEMA_VERSION",
    "assemble_archive_pack_units",
    "select_pilot_tickers",
    "write_cold_objects",
]
