"""Peer model pass table from sibling ``screen_run_manifest.json`` files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from value_investor.storage import read_json, resolve_json_path, write_json

_RESEARCH_ROOTS = (
    Path("docs/data/research"),
    Path("output/research"),
)

_BUY_SIGNALS = frozenset({"strong_buy", "buy"})


def _research_roots(output_dir: Path | None) -> list[Path]:
    if output_dir is not None:
        return [Path(output_dir) / "research"]
    return list(_RESEARCH_ROOTS)


def _load_manifest(path: Path) -> dict[str, Any] | None:
    resolved = resolve_json_path(path)
    if resolved is None:
        return None
    try:
        payload = read_json(resolved)
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _iter_sibling_manifests(*, research_roots: list[Path]) -> list[tuple[str, dict[str, Any]]]:
    seen: set[str] = set()
    out: list[tuple[str, dict[str, Any]]] = []
    for root in research_roots:
        if not root.is_dir():
            continue
        for manifest_path in root.glob("*/sources/screen_run_manifest.json"):
            ticker = manifest_path.parent.parent.name
            key = ticker.upper()
            if key in seen:
                continue
            manifest = _load_manifest(manifest_path)
            if manifest is None:
                continue
            seen.add(key)
            out.append((ticker, manifest))
    return out


def build_peer_model_pass_table(
    ticker: str,
    *,
    sector: str | None = None,
    output_dir: Path | None = None,
    peer_signals: set[str] | None = None,
) -> dict[str, Any]:
    """
    Build a cross-ticker model pass comparison from sibling manifests.

    Peers share the anchor ticker's ``run_at`` stamp, match ``sector`` when
    provided, and sit in buy tiers (``strong_buy`` / ``buy`` by default).
    """
    ticker = ticker.strip().upper()
    allowed_signals = peer_signals or _BUY_SIGNALS
    roots = _research_roots(output_dir)
    siblings = _iter_sibling_manifests(research_roots=roots)

    anchor_run_at: str | None = None
    for peer_ticker, manifest in siblings:
        if peer_ticker.upper() == ticker:
            anchor_run_at = str(manifest.get("run_at") or "")
            break

    peers: list[dict[str, Any]] = []
    model_ids: set[str] = set()

    for peer_ticker, manifest in siblings:
        if anchor_run_at and str(manifest.get("run_at") or "") != anchor_run_at:
            continue
        ticker_signal = manifest.get("ticker_signal") or {}
        peer_sector = str(ticker_signal.get("sector") or "")
        if sector and peer_sector and peer_sector != sector:
            continue
        peer_signal = str(
            ticker_signal.get("adjusted_signal") or ticker_signal.get("signal") or ""
        ).lower()
        if peer_signal not in allowed_signals:
            continue

        models = manifest.get("ticker_models") or []
        passes = {
            str(row.get("model_id")): bool(row.get("passed"))
            for row in models
            if row.get("model_id")
        }
        scores = {
            str(row.get("model_id")): row.get("score") for row in models if row.get("model_id")
        }
        model_ids.update(passes.keys())
        peers.append(
            {
                "ticker": peer_ticker,
                "signal": peer_signal,
                "models_passed": manifest.get("models_passed")
                or ticker_signal.get("models_passed"),
                "model_passes": passes,
                "model_scores": scores,
            }
        )

    peers.sort(key=lambda row: (-int(float(row.get("models_passed") or 0)), str(row["ticker"])))

    model_rows: list[dict[str, Any]] = []
    for model_id in sorted(model_ids):
        peer_passes = {peer["ticker"]: peer["model_passes"].get(model_id) for peer in peers}
        peer_scores = {peer["ticker"]: peer["model_scores"].get(model_id) for peer in peers}
        passed_count = sum(1 for value in peer_passes.values() if value)
        model_rows.append(
            {
                "model_id": model_id,
                "passed_count": passed_count,
                "peer_count": len(peers),
                "peer_passes": peer_passes,
                "peer_scores": peer_scores,
            }
        )

    return {
        "ticker": ticker,
        "sector": sector,
        "run_at": anchor_run_at,
        "peer_count": len(peers),
        "peers": peers,
        "model_rows": model_rows,
        "attached": bool(peers),
    }


def ensure_sector_peer_manifests(
    ticker: str,
    *,
    sector: str | None = None,
    output_dir: Path | None = None,
    market: str | None = None,
) -> int:
    """
    Write missing ``screen_run_manifest.json`` files for sector buy-tier peers.

    Gap-fill often attaches a manifest for one ticker only; sibling manifests
    are materialized from the latest committed history run so peer tables work.
    """
    from value_investor.research.gap_fill_sources import (
        _latest_history_run_paths,
        attach_screen_run_manifest,
    )
    from value_investor.storage import COMMITTED_HISTORY_DIR

    ticker = ticker.strip().upper()
    roots = [root for root in _research_roots(output_dir) if root.is_dir()]
    if not roots:
        return 0

    anchor_manifest: dict[str, Any] | None = None
    for root in roots:
        anchor_manifest = _load_manifest(root / ticker / "sources" / "screen_run_manifest.json")
        if anchor_manifest is not None:
            break

    primary_root = roots[0]
    if anchor_manifest is None:
        sources = primary_root / ticker / "sources"
        attach_screen_run_manifest(sources, ticker, market=market or "ftse350")
        anchor_manifest = _load_manifest(sources / "screen_run_manifest.json")

    if not anchor_manifest:
        return 0

    run_at = str(anchor_manifest.get("run_at") or "")
    ticker_signal = anchor_manifest.get("ticker_signal") or {}
    effective_sector = sector or str(ticker_signal.get("sector") or "")
    if not run_at or not effective_sector:
        return 0

    paired = _latest_history_run_paths(COMMITTED_HISTORY_DIR)
    if paired is None:
        return 0
    run_path, _models_path = paired
    try:
        run_payload = read_json(run_path)
    except (OSError, ValueError, TypeError):
        return 0
    if str(run_payload.get("run_at") or "") != run_at:
        return 0

    peer_tickers: set[str] = set()
    for row in run_payload.get("signals") or []:
        if str(row.get("sector") or "") != effective_sector:
            continue
        peer_signal = str(row.get("adjusted_signal") or row.get("signal") or "").lower()
        if peer_signal not in _BUY_SIGNALS:
            continue
        peer = str(row.get("ticker") or "").strip().upper()
        if peer:
            peer_tickers.add(peer)

    written = 0
    for peer in sorted(peer_tickers):
        already_present = False
        for root in roots:
            manifest = _load_manifest(root / peer / "sources" / "screen_run_manifest.json")
            if manifest is not None and str(manifest.get("run_at") or "") == run_at:
                already_present = True
                break
        if already_present:
            continue
        attach_screen_run_manifest(
            primary_root / peer / "sources",
            peer,
            market=market or "ftse350",
        )
        written += 1
    return written


def attach_peer_model_pass_table(
    sources_dir: Path,
    ticker: str,
    *,
    sector: str | None = None,
    output_dir: Path | None = None,
    market: str | None = None,
) -> dict[str, Any]:
    """Write ``peer_model_pass_table.json`` beside gap-fill source packs."""
    ensure_sector_peer_manifests(
        ticker,
        sector=sector,
        output_dir=output_dir,
        market=market,
    )
    table = build_peer_model_pass_table(
        ticker,
        sector=sector,
        output_dir=output_dir,
    )
    sources_dir = Path(sources_dir)
    sources_dir.mkdir(parents=True, exist_ok=True)
    path = sources_dir / "peer_model_pass_table.json"
    write_json(path, table, compact=False, compress=False)
    table["manifest_path"] = str(path)
    return table
