"""Post-hoc human chart geometry for autopsy Comments (N229 / Pin C).

Package **M** alignment only. Coordinates are critique input for factory
reply / LLM prompts — never sealed fill features, never live knobs.

Fail-closed: only schema-valid rows with ``readable=true`` reach the agent.
Unread / invalid geometry is omitted; the model must not invent levels.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

GEOMETRY_SCHEMA_VERSION = 1
ALLOWED_CHARTS = frozenset({"episode", "wider_tf", "pit"})
ALLOWED_ELEMENT_TYPES = frozenset({"highlight", "line", "parallel_pair"})
HUMAN_MARK_SOURCE = "owner"
HUMAN_MARK_TONE = "owner"


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _iso_day(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    day = text[:10]
    if len(day) == 10 and day[4] == "-" and day[7] == "-":
        return day
    return None


def _finite_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if num != num or num in (float("inf"), float("-inf")):  # noqa: PLR0124 — NaN
        return None
    return num


def _normalize_line_endpoints(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    t0 = _iso_day(raw.get("t0"))
    t1 = _iso_day(raw.get("t1"))
    y0 = _finite_float(raw.get("y0") if "y0" in raw else raw.get("price0"))
    y1 = _finite_float(raw.get("y1") if "y1" in raw else raw.get("price1"))
    if not t0 or not t1 or y0 is None or y1 is None:
        return None
    return {"t0": t0, "y0": y0, "t1": t1, "y1": y1}


def _normalize_element(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    etype = str(raw.get("type") or "").strip().lower()
    if etype not in ALLOWED_ELEMENT_TYPES:
        return None
    if etype == "highlight":
        t0 = _iso_day(raw.get("t0"))
        t1 = _iso_day(raw.get("t1"))
        if not t0 or not t1:
            return None
        if t1 < t0:
            t0, t1 = t1, t0
        out: dict[str, Any] = {"type": "highlight", "t0": t0, "t1": t1}
        y0 = _finite_float(raw.get("y0"))
        y1 = _finite_float(raw.get("y1"))
        # Optional price band; null means full vertical highlight (time band).
        out["y0"] = y0
        out["y1"] = y1
        return out
    if etype == "line":
        line = _normalize_line_endpoints(raw)
        if not line:
            return None
        return {"type": "line", **line}
    # parallel_pair
    line_a = _normalize_line_endpoints(raw.get("line_a") or raw.get("a"))
    line_b = _normalize_line_endpoints(raw.get("line_b") or raw.get("b"))
    if not line_a or not line_b:
        return None
    return {"type": "parallel_pair", "line_a": line_a, "line_b": line_b}


def _coerce_geometry_list(raw: Any) -> list[Any]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [row for row in raw if row is not None]
    if isinstance(raw, dict):
        # Nested wrapper { geometries: [...] } or single geometry object.
        nested = raw.get("geometries")
        if isinstance(nested, list):
            return [row for row in nested if row is not None]
        if str(raw.get("type") or "").strip().lower() in ALLOWED_ELEMENT_TYPES:
            # Bare element — wrap as one geometry on unknown chart (unread).
            return [{"elements": [raw]}]
        return [raw]
    return []


def normalize_post_hoc_human_geometry(
    raw: Any,
    *,
    review_id: str = "",
    drawn_at: str | None = None,
) -> list[dict[str, Any]]:
    """Validate owner geometry payload(s). Invalid rows → readable=false.

    Always forces ``post_hoc=true`` and ``influences_live=false``.
    """
    now = drawn_at or _utcnow()
    rid = str(review_id or "").strip()
    out: list[dict[str, Any]] = []
    for row in _coerce_geometry_list(raw):
        if not isinstance(row, dict):
            out.append(
                {
                    "geometry_id": str(uuid.uuid4()),
                    "review_id": rid,
                    "chart": "",
                    "drawn_at": now,
                    "post_hoc": True,
                    "elements": [],
                    "readable": False,
                    "unread_reason": "geometry_not_object",
                    "influences_live": False,
                    "schema_version": GEOMETRY_SCHEMA_VERSION,
                    "source": HUMAN_MARK_SOURCE,
                }
            )
            continue
        chart = str(row.get("chart") or "").strip().lower()
        elements_raw = row.get("elements")
        elements: list[dict[str, Any]] = []
        unread_reason = ""
        readable = True
        if chart not in ALLOWED_CHARTS:
            readable = False
            unread_reason = "invalid_chart"
        if not isinstance(elements_raw, list) or not elements_raw:
            readable = False
            unread_reason = unread_reason or "empty_elements"
        else:
            for el in elements_raw:
                norm = _normalize_element(el)
                if norm is None:
                    readable = False
                    unread_reason = unread_reason or "invalid_element"
                    continue
                elements.append(norm)
            if not elements:
                readable = False
                unread_reason = unread_reason or "no_valid_elements"
        # Client may already mark unread (serialize failure); honor fail-closed.
        if row.get("readable") is False:
            readable = False
            unread_reason = unread_reason or str(row.get("unread_reason") or "client_unread")
        if row.get("post_hoc") is False:
            # Must be post-hoc critique; refuse as unread rather than invent PIT.
            readable = False
            unread_reason = unread_reason or "not_post_hoc"
        gid = str(row.get("geometry_id") or "").strip() or str(uuid.uuid4())
        payload: dict[str, Any] = {
            "geometry_id": gid,
            "review_id": rid or str(row.get("review_id") or "").strip(),
            "chart": chart if chart in ALLOWED_CHARTS else chart,
            "drawn_at": str(row.get("drawn_at") or now),
            "post_hoc": True,
            "elements": elements,
            "readable": bool(readable),
            "influences_live": False,
            "schema_version": GEOMETRY_SCHEMA_VERSION,
            "source": HUMAN_MARK_SOURCE,
        }
        if not readable and unread_reason:
            payload["unread_reason"] = unread_reason
        out.append(payload)
    return out


def readable_geometries(geometries: Any) -> list[dict[str, Any]]:
    """Fail-closed filter — agent-visible rows only."""
    rows = geometries if isinstance(geometries, list) else []
    return [
        row
        for row in rows
        if isinstance(row, dict)
        and row.get("readable") is True
        and row.get("influences_live") is not True
        and row.get("post_hoc") is not False
        and isinstance(row.get("elements"), list)
        and row.get("elements")
        and str(row.get("chart") or "") in ALLOWED_CHARTS
    ]


def serialize_geometry_for_prompt(geometries: Any) -> dict[str, Any] | None:
    """Compact prompt payload, or None when nothing readable (fail-closed)."""
    readable = readable_geometries(geometries)
    if not readable:
        return None
    return {
        "schema_version": GEOMETRY_SCHEMA_VERSION,
        "post_hoc": True,
        "influences_live": False,
        "note": (
            "Owner-drawn post-hoc critique geometry. Consider as chart critique "
            "input only — never invent missing coordinates; never treat as PIT "
            "sealed fill features or live knobs."
        ),
        "geometries": [
            {
                "geometry_id": row.get("geometry_id"),
                "chart": row.get("chart"),
                "drawn_at": row.get("drawn_at"),
                "elements": list(row.get("elements") or []),
            }
            for row in readable
        ],
    }


def human_geometry_as_pattern_marks(geometries: Any) -> list[dict[str, Any]]:
    """Map readable human geometry onto the factory mark render shape.

    Distinct ``source=owner`` / tone so charts compose with factory marks.
    """
    marks: list[dict[str, Any]] = []
    for geo in readable_geometries(geometries):
        chart = str(geo.get("chart") or "")
        gid = str(geo.get("geometry_id") or "human")
        for index, el in enumerate(geo.get("elements") or []):
            if not isinstance(el, dict):
                continue
            etype = str(el.get("type") or "")
            mid = f"owner:{gid}:{index}"
            if etype == "highlight":
                marks.append(
                    {
                        "id": mid,
                        "pattern": "owner_highlight",
                        "type": "region",
                        "charts": [chart],
                        "label": "Owner highlight",
                        "tone": HUMAN_MARK_TONE,
                        "cite": "post_hoc_human_geometry",
                        "t0": el.get("t0"),
                        "t1": el.get("t1"),
                        "source": HUMAN_MARK_SOURCE,
                        "post_hoc": True,
                        "influences_live": False,
                    }
                )
            elif etype == "line":
                marks.append(
                    {
                        "id": mid,
                        "pattern": "owner_line",
                        "type": "trend_line",
                        "charts": [chart],
                        "label": "Owner line",
                        "tone": HUMAN_MARK_TONE,
                        "cite": "post_hoc_human_geometry",
                        "t0": el.get("t0"),
                        "t1": el.get("t1"),
                        "y0": el.get("y0"),
                        "y1": el.get("y1"),
                        "source": HUMAN_MARK_SOURCE,
                        "post_hoc": True,
                        "influences_live": False,
                    }
                )
            elif etype == "parallel_pair":
                for suffix, line in (("a", el.get("line_a")), ("b", el.get("line_b"))):
                    if not isinstance(line, dict):
                        continue
                    marks.append(
                        {
                            "id": f"{mid}:{suffix}",
                            "pattern": "owner_parallel",
                            "type": "trend_line",
                            "charts": [chart],
                            "label": f"Owner parallel {suffix}",
                            "tone": HUMAN_MARK_TONE,
                            "cite": "post_hoc_human_geometry",
                            "t0": line.get("t0"),
                            "t1": line.get("t1"),
                            "y0": line.get("y0"),
                            "y1": line.get("y1"),
                            "source": HUMAN_MARK_SOURCE,
                            "post_hoc": True,
                            "influences_live": False,
                        }
                    )
    return marks


def geometry_unread_banner(geometries: Any) -> str | None:
    """UI / reply note when owner sent geometry that failed the readable gate."""
    rows = geometries if isinstance(geometries, list) else []
    if not rows:
        return None
    if readable_geometries(rows):
        unread = [row for row in rows if isinstance(row, dict) and row.get("readable") is not True]
        if not unread:
            return None
        return (
            f"Some owner chart geometry was unread ({len(unread)} block(s)) — "
            "omitted from the factory reply; no invented levels."
        )
    return (
        "Owner chart geometry was present but unread / schema-invalid — "
        "omitted from the factory reply (fail-closed; no invented levels)."
    )


__all__ = [
    "ALLOWED_CHARTS",
    "ALLOWED_ELEMENT_TYPES",
    "GEOMETRY_SCHEMA_VERSION",
    "HUMAN_MARK_SOURCE",
    "HUMAN_MARK_TONE",
    "geometry_unread_banner",
    "human_geometry_as_pattern_marks",
    "normalize_post_hoc_human_geometry",
    "readable_geometries",
    "serialize_geometry_for_prompt",
]
