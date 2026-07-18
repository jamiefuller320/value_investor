"""Optional FIRDS MIC filtering for II-advertised venues.

Public FCA/ESMA FIRDS files list instruments admitted on trading venues (ISIN + MIC).
Filtering by Interactive Investor's advertised exchange MICs is a legal enrichment
layer — it does **not** prove II will accept an order for that ISIN.
"""

from __future__ import annotations

import csv
import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable

from value_investor.ii_coverage import ii_coverage_root, load_ii_policy
from value_investor.storage import write_json

logger = logging.getLogger(__name__)


def ii_allowed_mics(policy: dict[str, Any] | None = None) -> set[str]:
    """Return MIC codes for online-dealable II venues (exclude phone-only)."""
    policy = policy or load_ii_policy()
    mics: set[str] = set()
    for row in policy.get("exchanges") or []:
        if row.get("phone_only"):
            continue
        if not row.get("online_dealable", True):
            continue
        for mic in row.get("mics") or []:
            mics.add(str(mic).strip().upper())
    return mics


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def iter_firds_xml_rows(path: Path) -> Iterable[dict[str, str]]:
    """Yield ISIN/MIC/name rows from a FIRDS XML dump (streaming)."""
    context = ET.iterparse(path, events=("end",))
    for _event, elem in context:
        if _local(elem.tag) not in {"RefData", "FinInstrm", "ModfdRcrd", "NewRcrd"}:
            # Keep walking; many FIRDS schemas nest RefData differently.
            pass
        # Collect when we see an ISIN-bearing leaf cluster.
        isin = None
        mic = None
        name = None
        for child in elem.iter():
            local = _local(child.tag)
            text = (child.text or "").strip()
            if not text:
                continue
            if local in {"ISIN", "Id"} and len(text) == 12 and text[:2].isalpha():
                # Prefer explicit ISIN tags; Id may also be used.
                if local == "ISIN" or (local == "Id" and isin is None):
                    isin = text
            elif local in {"TradgVn", "TrdgVn", "Id"} and len(text) == 4 and text.isalpha():
                if local != "Id" or mic is None:
                    mic = text.upper()
            elif local in {"FullNm", "ShrtNm", "Nm"} and name is None:
                name = text
        if isin and mic:
            yield {"isin": isin, "mic": mic, "name": name or ""}
        # Free memory for huge files
        if _local(elem.tag) in {"RefData", "FinInstrm", "ModfdRcrd", "NewRcrd", "TermntdRcrd"}:
            elem.clear()


def iter_firds_csv_rows(path: Path) -> Iterable[dict[str, str]]:
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            # Tolerate common header variants
            isin = (
                row.get("ISIN")
                or row.get("isin")
                or row.get("Id")
                or row.get("InstrumentIdentificationCode")
            )
            mic = (
                row.get("TradingVenue")
                or row.get("MIC")
                or row.get("mic")
                or row.get("Venue")
            )
            name = row.get("FullName") or row.get("Name") or row.get("full_name") or ""
            if isin and mic:
                yield {
                    "isin": str(isin).strip(),
                    "mic": str(mic).strip().upper(),
                    "name": str(name).strip(),
                }


def filter_firds_file(
    input_path: Path,
    *,
    mics: set[str] | None = None,
    limit: int | None = None,
) -> list[dict[str, str]]:
    """Return FIRDS rows whose MIC is in the II online allowlist."""
    allowed = mics or ii_allowed_mics()
    path = Path(input_path)
    if not path.exists():
        raise FileNotFoundError(path)
    iterator: Iterable[dict[str, str]]
    suffix = path.suffix.lower()
    if suffix == ".xml":
        iterator = iter_firds_xml_rows(path)
    elif suffix in {".csv", ".txt"}:
        iterator = iter_firds_csv_rows(path)
    else:
        raise ValueError(f"Unsupported FIRDS file type: {suffix} (use .xml or .csv)")

    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in iterator:
        mic = row["mic"]
        if mic not in allowed:
            continue
        key = (row["isin"], mic)
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
        if limit is not None and len(out) >= limit:
            break
    return out


def write_firds_filter_result(
    rows: list[dict[str, str]],
    *,
    library_root: Path | None = None,
    source_path: Path | None = None,
) -> Path:
    ii_root = ii_coverage_root(library_root)
    payload = {
        "schema_version": 1,
        "source_path": str(source_path) if source_path else None,
        "mics": sorted(ii_allowed_mics()),
        "row_count": len(rows),
        "note": (
            "FIRDS rows on II-advertised online MICs. Venue admission ≠ II order acceptance."
        ),
        "rows": rows,
    }
    path = ii_root / "firds_ii_mics.json"
    write_json(path, payload, compact=True)
    # Also CSV for easy joins
    csv_path = ii_root / "firds_ii_mics.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["isin", "mic", "name"])
        writer.writeheader()
        writer.writerows(rows)
    logger.info("Wrote %d FIRDS rows → %s", len(rows), path)
    return path
