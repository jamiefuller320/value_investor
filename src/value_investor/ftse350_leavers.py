"""FTSE 350 delisting leavers, 2013-01-01 to 2025-09-30.

The source is the FTSE Russell historic addition and deletion change logs (FTSE 100
and FTSE 250). A leaver left the FTSE 350 because of a delisting: a takeover, a
failure, or a move of listing. A deletion that is only an index demotion or
promotion, with the company still listed, is not a leaver.
"""

from __future__ import annotations

import difflib
import json
import re
from collections import defaultdict
from datetime import date

WINDOW_START = date(2013, 1, 1)
WINDOW_END = date(2025, 9, 30)
FTSE100_HISTORY_URL = (
    "https://www.lseg.com/content/dam/ftse-russell/en_us/documents/"
    "policy-documents/ftse-100-constituent-history.pdf"
)
FTSE250_HISTORY_URL = (
    "https://www.lseg.com/content/dam/ftse-russell/en_us/documents/"
    "policy-documents/ftse-250-constituent-history.pdf"
)
WIKIPEDIA_PAST_CONSTITUENTS_URL = "https://en.wikipedia.org/wiki/FTSE_100_Index#Past_constituents"
UK_JURISDICTIONS = {
    "england-wales",
    "england",
    "wales",
    "scotland",
    "northern-ireland",
    "united-kingdom",
    "uk",
}
_NON_UK_RE = re.compile(
    r"(?:incorporat(?:ed|ion)|based in|domiciled in|headquartered in|registered in)"
    r"[^.]{0,60}\b("
    r"Jersey|Guernsey|Isle of Man|Bermuda|Cayman Islands|Cayman|Luxembourg|"
    r"the Netherlands|Netherlands|Switzerland|Ireland|Australia|Canada|"
    r"South Africa|Cyprus|Mauritius|British Virgin|Gibraltar|Singapore|Israel|"
    r"Germany|Austria"
    r")\b|location_country\s*=\s*("
    r"Jersey|Guernsey|Isle of Man|Bermuda|Cayman Islands|Netherlands|"
    r"Switzerland|Ireland|Australia|Luxembourg|Canada|South Africa|Germany)",
    re.I,
)
_ADJ_PLACE_RE = re.compile(
    r"\b(Irish|German|Dutch|Swiss|Bermudian|Canadian|Australian)\b"
    r"[^.]{0,40}\b(company|group|firm|bank|plc|multinational|operator)\b",
    re.I,
)
_ADJ_PLACE = {
    "irish": "Ireland",
    "german": "Germany",
    "dutch": "Netherlands",
    "swiss": "Switzerland",
    "bermudian": "Bermuda",
    "canadian": "Canada",
    "australian": "Australia",
}
GENERIC = {
    "plc",
    "limited",
    "ltd",
    "inc",
    "nv",
    "sa",
    "ag",
    "se",
    "the",
    "and",
    "of",
    "corporation",
    "corp",
    "company",
    "co",
}
TAKEOVER_RE = re.compile(
    r"acqui|take-?over|scheme of arrangement|scheme of reconstruction|cash offer|\boffer\b|(?<!de)merger|"
    r"recommended offer|\bcombination\b",
    re.I,
)
FAILURE_RE = re.compile(
    r"administration|liquidation|winding[- ]up|continued suspension|"
    r"suspension of listing|in administration",
    re.I,
)
MOVE_RE = re.compile(
    r"nationality|change of listing|listing categor|transfer of .{0,40}shares|"
    r"ineligible standard|unification|moved (its )?listing|switch of listing|"
    r"simplification of the share structure|premium to standard|standard to premium|"
    r"listing category",
    re.I,
)
EXCLUDE_NOTE_RE = re.compile(
    r"re-?ranking|temporarily retained|dummy line|dummy|fast entry",
    re.I,
)


def words(text: str) -> str:
    s = (text or "").lower().replace("&", " and ")
    s = s.replace("*", " ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def normalise_name(name: str) -> str:
    tokens = [t for t in words(name).split() if t not in GENERIC and not t.isdigit()]
    return " ".join(tokens)


def _token_in_note(token: str, note_tokens: list[str]) -> bool:
    if token in note_tokens:
        return True
    if len(token) < 5:
        return False
    for other in note_tokens:
        if abs(len(other) - len(token)) > 2:
            continue
        if difflib.SequenceMatcher(None, token, other).ratio() >= 0.84:
            return True
    return False


def mentioned(deleted: str, notes: str) -> bool:
    note_tokens = words(notes).split()
    tokens = [t for t in normalise_name(deleted).split() if len(t) >= 3]
    if not tokens:
        tokens = [t for t in words(deleted).split() if t not in GENERIC]
    if not tokens or not note_tokens:
        return False
    if len(tokens) == 1 and len(tokens[0]) <= 3:
        return bool(re.search(rf"\b{re.escape(tokens[0])}\b", " ".join(note_tokens)))
    hits = [t for t in tokens[:4] if _token_in_note(t, note_tokens)]
    # A trailing "communications"/"holdings" can be absent from the note.
    needed = (
        1 if len(tokens) == 1 else max(1, min(len(tokens), 2) if len(tokens) > 2 else len(tokens))
    )
    if len(tokens) > 2:
        needed = len(tokens) - 1
    return len(hits) >= needed


def _named_party(notes: str, pattern: str) -> str:
    match = re.search(pattern, notes, flags=re.I)
    if not match:
        return ""
    return normalise_name(match.group(1))


def classify_note(deleted: str, notes: str, added: str = "") -> str | None:
    """Return takeover, failure, other, or None when the row is not a delisting."""
    if not deleted or not deleted.strip():
        return None
    low_name = deleted.lower()
    low_notes = (notes or "").lower()
    if "dummy" in low_name or "distribution line" in low_name or "temporary line" in low_name:
        return None
    if not low_notes.strip():
        return None
    if re.search(r"incorrect addition|temporary line|secondary line|rebalance", low_notes):
        return None
    if EXCLUDE_NOTE_RE.search(notes) and not FAILURE_RE.search(notes):
        return None
    demerged = _named_party(notes, r"demerger of ([^.]{0,80}?) from\b")
    if "nationality" in low_notes and "demerger" in low_notes:
        if not demerged or not (mentioned(deleted, demerged) or mentioned(demerged, deleted)):
            return "other"
    if "demerger" in low_notes:
        # The parent stays listed. A temporary spun-off line is not a leaver.
        if demerged and (mentioned(deleted, demerged) or mentioned(demerged, deleted)):
            return None
        if (
            "temporary" in low_notes
            or "non-constituent" in low_notes
            or "non constituent" in low_notes
        ):
            return None
        if not TAKEOVER_RE.search(notes):
            return None
    name_in_note = mentioned(deleted, notes)
    target = _named_party(
        notes,
        r"(?:acquisition|offer|cash offer|merger|combination|transfer) (?:of|for|between) ([^.]{0,90}?)(?: by | with | and | from |$)",
    )
    target_is_deleted = bool(target) and (mentioned(deleted, target) or mentioned(target, deleted))
    target_is_other = bool(target) and not target_is_deleted
    if FAILURE_RE.search(notes) and (
        name_in_note or target_is_deleted or "deleted following" in low_notes
    ):
        return "failure"
    if MOVE_RE.search(notes) and (name_in_note or target_is_deleted or "nationality" in low_notes):
        if not target_is_other:
            return "other"
    if re.search(r"scheme of reconstruction", notes, re.I) and (name_in_note or target_is_deleted):
        return "failure" if FAILURE_RE.search(notes) else "takeover"
    if TAKEOVER_RE.search(notes) and (name_in_note or target_is_deleted):
        return "takeover"
    # "Cash acquisition by X" names the buyer, not the target. The deleted row is the target.
    buyer_only = bool(re.search(r"\b(?:acquisition|offer)\b", notes, re.I)) and " by " in low_notes
    if TAKEOVER_RE.search(notes) and not target and buyer_only:
        if not re.search(r"\b(?:demerger|acquisition|offer) of\b", notes, re.I):
            return "takeover"
    deleted_tokens = set(normalise_name(deleted).split())
    added_tokens = set(normalise_name(added).split())
    if (
        deleted_tokens
        and added_tokens
        and deleted_tokens < added_tokens
        and re.search(r"combination|(?<!de)merger", notes, re.I)
    ):
        return "takeover"
    return None


def _merge_ok(a: str, b: str) -> bool:
    if a == b:
        return True
    if not a or not b:
        return False
    ta, tb = a.split(), b.split()
    if abs(len(ta) - len(tb)) == 1:
        longer, shorter = (ta, tb) if len(ta) > len(tb) else (tb, ta)
        extra = [t for t in longer if t not in shorter]
        if len(extra) == 1 and len(extra[0]) <= 2:
            return False
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.96


class _Union:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def add(self, key: str) -> None:
        self.parent.setdefault(key, key)

    def find(self, key: str) -> str:
        self.add(key)
        while self.parent[key] != key:
            self.parent[key] = self.parent[self.parent[key]]
            key = self.parent[key]
        return key

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            # Prefer the longer spelling as the root so ligature drops lose.
            if len(rb) > len(ra):
                ra, rb = rb, ra
            self.parent[rb] = ra


def cluster_keys(names: list[str]) -> dict[str, str]:
    uniq = sorted({n for n in names if n})
    uf = _Union()
    for name in uniq:
        uf.add(name)
    for i, left in enumerate(uniq):
        for right in uniq[i + 1 :]:
            if _merge_ok(left, right):
                uf.union(left, right)
    return {name: uf.find(name) for name in uniq}


def select_leavers(events: list[dict]) -> tuple[list[dict], dict]:
    """Return delisting leavers and a diagnostic dict. Events need date/index/added/deleted/notes."""
    prepared = []
    for event in events:
        prepared.append(
            {
                **event,
                "added_key": normalise_name(event.get("added") or ""),
                "deleted_key": normalise_name(event.get("deleted") or ""),
                "date": event["date"],
            }
        )
    keys = [row["added_key"] for row in prepared] + [row["deleted_key"] for row in prepared]
    clusters = cluster_keys(keys)

    def cid(key: str) -> str:
        return clusters.get(key, key) if key else ""

    for row in prepared:
        row["added_id"] = cid(row["added_key"])
        row["deleted_id"] = cid(row["deleted_key"])
    prepared.sort(key=lambda row: (row["date"], 0 if row["index"] == "ftse100" else 1))

    # Same-day deletions of one id on both indexes are copies, not initial membership.
    twin_deletes: set[tuple[str, str, str]] = set()
    seen_del: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in prepared:
        if row["deleted_id"]:
            seen_del[(row["date"], row["deleted_id"])].add(row["index"])
    for (iso, ident), indexes in seen_del.items():
        if len(indexes) > 1:
            for index in indexes:
                twin_deletes.add((iso, index, ident))

    members: dict[str, set[str]] = {"ftse100": set(), "ftse250": set()}
    first_seen: dict[tuple[str, str], str] = {}
    for row in prepared:
        if row["added_id"] and (row["index"], row["added_id"]) not in first_seen:
            first_seen[(row["index"], row["added_id"])] = "add"
        if (
            row["deleted_id"]
            and (row["index"], row["deleted_id"]) not in first_seen
            and (row["date"], row["index"], row["deleted_id"]) not in twin_deletes
        ):
            first_seen[(row["index"], row["deleted_id"])] = "delete"
    for (index, ident), kind in first_seen.items():
        if kind == "delete":
            members[index].add(ident)

    # Remove implied membership created only by a same-day copy of the other index's deletion.
    by_date: dict[str, list[dict]] = defaultdict(list)
    for row in prepared:
        by_date[row["date"]].append(row)

    diagnostics = {
        "repairs": [],
        "dropped_duplicate_rows": [],
        "uncertain_exits": [],
        "transfers": [],
    }

    exits: list[dict] = []
    # Track last add date per id so first_in_spell can be recovered.
    spell_start: dict[str, str] = {}
    for ident in set(members["ftse100"]) | set(members["ftse250"]):
        spell_start[ident] = "1984-01-19" if ident in members["ftse100"] else "2002-09-23"

    dates = sorted(by_date)
    for iso in dates:
        day = by_date[iso]
        # Repair using membership at the start of the day.
        drop_ids: set[int] = set()
        for row in day:
            ident = row["deleted_id"]
            if not ident:
                continue
            other = "ftse250" if row["index"] == "ftse100" else "ftse100"
            in_this = ident in members[row["index"]]
            in_other = ident in members[other]
            twin = [
                other_row
                for other_row in day
                if other_row is not row
                and other_row["index"] == other
                and other_row["deleted_id"] == ident
            ]
            if not twin:
                continue
            twin_row = twin[0]
            if in_this and not in_other:
                # This is the real index. If the twin is an identical add/delete, drop the twin.
                if twin_row["added_id"] == row["added_id"]:
                    drop_ids.add(id(twin_row))
                    diagnostics["dropped_duplicate_rows"].append(
                        {"date": iso, "deleted": row.get("deleted"), "index": twin_row["index"]}
                    )
                continue
            if in_other and not in_this:
                # Spurious deletion on this index.
                added_on_real = [
                    other_row["added_id"]
                    for other_row in day
                    if other_row["index"] == other
                    and other_row["added_id"] in members[row["index"]]
                ]
                if twin_row["added_id"] == row["added_id"]:
                    drop_ids.add(id(row))
                    diagnostics["dropped_duplicate_rows"].append(
                        {"date": iso, "deleted": row.get("deleted"), "index": row["index"]}
                    )
                elif added_on_real:
                    replacement = added_on_real[0]
                    diagnostics["repairs"].append(
                        {
                            "date": iso,
                            "index": row["index"],
                            "from": row.get("deleted"),
                            "to_id": replacement,
                        }
                    )
                    row["deleted_id"] = replacement
                    row["deleted"] = replacement
                    row["repaired"] = True
        usable = [row for row in day if id(row) not in drop_ids]
        end_members = {index: set(ids) for index, ids in members.items()}
        for row in usable:
            if row["deleted_id"]:
                end_members[row["index"]].discard(row["deleted_id"])
            if row["added_id"]:
                end_members[row["index"]].add(row["added_id"])
        # Adds within 7 days are applied later; mark pending deletes and resolve after the window.
        for row in usable:
            ident = row["deleted_id"]
            if not ident:
                continue
            still = ident in end_members["ftse100"] or ident in end_members["ftse250"]
            kind_now = classify_note(
                str(row.get("deleted") or ""),
                str(row.get("notes") or ""),
                str(row.get("added") or ""),
            )
            # A delisting note still counts when the other index's membership bit is stale
            # (the promotion row was missing). A same-day add of the same id is removed later.
            if still and not kind_now:
                continue
            exits.append(row)
        # Spell starts for additions that were not members at the start of the day.
        for row in usable:
            if row["added_id"] and row["added_id"] not in members["ftse100"] | members["ftse250"]:
                spell_start[row["added_id"]] = iso
            elif row["added_id"] and row["added_id"] not in members[row["index"]]:
                # Joined this index. If they were not in the other, the spell starts today.
                other = "ftse250" if row["index"] == "ftse100" else "ftse100"
                if row["added_id"] not in members[other]:
                    spell_start[row["added_id"]] = iso
        members = end_members

    # Cancel exits that are followed by an add of the same id within 7 days (promotion/demotion lag).
    adds_by_id: dict[str, list[str]] = defaultdict(list)
    for row in prepared:
        if row["added_id"]:
            adds_by_id[row["added_id"]].append(row["date"])
    kept = []
    for row in exits:
        ident = row["deleted_id"]
        deleted_on = date.fromisoformat(row["date"])
        returned = False
        for iso in adds_by_id.get(ident, []):
            gap = (date.fromisoformat(iso) - deleted_on).days
            if 0 <= gap <= 7:
                returned = True
                diagnostics["transfers"].append(
                    {"date": row["date"], "name": row.get("deleted"), "added_on": iso}
                )
                break
        if returned:
            continue
        kind = classify_note(
            str(row.get("deleted") or ""),
            str(row.get("notes") or ""),
            str(row.get("added") or ""),
        )
        if kind is None and (row.get("notes") or "").strip() and not row.get("repaired"):
            diagnostics["uncertain_exits"].append(
                {
                    "date": row["date"],
                    "index": row["index"],
                    "deleted": row.get("deleted"),
                    "added": row.get("added"),
                    "notes": row.get("notes"),
                }
            )
        if kind is None:
            continue
        if not (WINDOW_START.isoformat() <= row["date"] <= WINDOW_END.isoformat()):
            continue
        # If a later exit exists, the caller keeps the last one.
        kept.append({**row, "reason_class": kind, "spell_start": spell_start.get(ident, "")})

    # Last delisting exit per id inside the window, and not a member at window end.
    by_id: dict[str, dict] = {}
    for row in kept:
        # Keep the last classified exit. The same name on both indexes the same day is one
        # company; the FTSE 100 row is the one the change log is authoritative for.
        prev = by_id.get(row["deleted_id"])
        if prev is None or row["date"] > prev["date"]:
            by_id[row["deleted_id"]] = row
        elif row["date"] == prev["date"] and row.get("index") == "ftse100":
            by_id[row["deleted_id"]] = row
    # Drop anyone who is a member on the day after WINDOW_END.
    # Approximate: if their last event at or before WINDOW_END is an add, they are still in.
    last_action: dict[str, tuple[str, str]] = {}
    for row in prepared:
        if row["date"] > WINDOW_END.isoformat():
            continue
        if row["added_id"]:
            last_action[row["added_id"]] = (row["date"], "add")
        if row["deleted_id"]:
            last_action[row["deleted_id"]] = (row["date"], "delete")
    leavers = []
    for ident, row in by_id.items():
        action = last_action.get(ident)
        if action and action[1] == "add" and action[0] >= row["date"]:
            continue
        leavers.append(row)
    # A FTSE 100 deletion that the 100 history omitted, named from the other index's note.
    present = {normalise_name(str(row.get("deleted") or "")) for row in leavers}
    omitted = re.compile(
        r"acquisition of ([A-Za-z0-9&.' -]{3,40}) \(FTSE (100|250)\)",
        re.I,
    )
    for event in events:
        if not (WINDOW_START.isoformat() <= event["date"] <= WINDOW_END.isoformat()):
            continue
        match = omitted.search(event.get("notes") or "")
        if not match:
            continue
        name = re.sub(r"\s+", " ", match.group(1)).strip(" -")
        if " from " in name.lower() or normalise_name(name) in present:
            continue
        if any(
            normalise_name(name) in normalise_name(str(row.get("deleted") or "")) for row in leavers
        ):
            continue
        leavers.append(
            {
                "date": event["date"],
                "index": "ftse" + match.group(2),
                "deleted": name,
                "added": "",
                "notes": event.get("notes") or "",
                "page": event.get("page"),
                "reason_class": "takeover",
                "deleted_id": normalise_name(name),
                "spell_start": "",
                "omitted_from_index_table": True,
            }
        )
        present.add(normalise_name(name))
        diagnostics.setdefault("omitted_rows", []).append({"date": event["date"], "name": name})
    leavers.sort(key=lambda row: (row["date"], row.get("deleted") or ""))
    return leavers, diagnostics


DATE_RE = re.compile(r"^(\d{1,2})-([A-Za-z]{3})-(\d{2})$")
MONTHS = {
    m: i
    for i, m in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1
    )
}


def _date_from_tokens(tokens: list[str]) -> str | None:
    blob = "".join(tokens).replace(" ", "")
    blob = re.sub(r"^(\d{1,2})([A-Za-z]{3})-(\d{2})$", r"\1-\2-\3", blob)
    blob = re.sub(r"^(\d{1,2})-([A-Za-z]{3})(\d{2})$", r"\1-\2-\3", blob)
    match = DATE_RE.match(blob)
    if not match:
        return None
    day, mon, yy = int(match.group(1)), MONTHS.get(match.group(2)), int(match.group(3))
    if mon is None:
        return None
    year = 1900 + yy if yy >= 80 else 2000 + yy
    try:
        return date(year, mon, day).isoformat()
    except ValueError:
        return None


def parse_history_pdf(path: str, index_name: str) -> list[dict]:
    import pymupdf

    doc = pymupdf.open(path)
    records: list[dict] = []
    for pi, page in enumerate(doc):
        if pi == 0:
            continue
        words = page.get_text("words")
        lines: list[list] = []
        for word in words:
            if lines and abs(lines[-1][0] - word[1]) < 2.0:
                lines[-1][1].append(word)
            else:
                lines.append([word[1], [word]])
        current: dict | None = None

        def flush() -> None:
            nonlocal current
            if current and current.get("date"):
                records.append(current)
            current = None

        for _y, ws in lines:
            ws = sorted(ws, key=lambda item: item[0])
            date_tokens = [item[4] for item in ws if item[0] < 90]
            iso = _date_from_tokens(date_tokens)
            if iso:
                flush()
                current = {
                    "date": iso,
                    "added": [],
                    "deleted": [],
                    "notes": [],
                    "index": index_name,
                    "page": pi + 1,
                }
            if current is None:
                continue
            for item in ws:
                x = item[0]
                if x < 90:
                    continue
                if x < 208:
                    current["added"].append(item[4])
                elif x < 345:
                    current["deleted"].append(item[4])
                else:
                    current["notes"].append(item[4])
        flush()
    doc.close()
    for record in records:
        for key in ("added", "deleted", "notes"):
            record[key] = re.sub(r"\s+", " ", " ".join(record[key])).strip()
        if record["added"] in {"-", "–", "—"}:
            record["added"] = ""
        if record["deleted"] in {"-", "–", "—"}:
            record["deleted"] = ""
    return records


# Glyphs dropped or doubled in the FTSE PDF text layer. The note is not used:
# it has its own typos ("Distributiojn", "Thomson" for Thompson).
_PDF_GLYPHS = {
    "smufit": "Smurfit",
    "loggistics": "Logistics",
    "brewer": "Brewin",
    "dophin": "Dolphin",
    "shaftebury": "Shaftesbury",
    "hochschid": "Hochschild",
    "distributiojn": "Distribution",
}


def display_name(deleted: str, notes: str) -> str:
    """Correct known PDF glyph errors. Otherwise keep the change-log name."""
    del notes
    cleaned = (deleted or "").replace("*", "").strip()
    return " ".join(_PDF_GLYPHS.get(token.lower().strip(".,"), token) for token in cleaned.split())


def first_year_in_window(spell_start: str) -> int:
    if not spell_start or spell_start < WINDOW_START.isoformat():
        return WINDOW_START.year
    return int(spell_start[:4])


def expected_years(spell_start: str, leaving_date: str) -> list[int]:
    start = max(2012, first_year_in_window(spell_start))
    end = int(leaving_date[:4])
    if end < start:
        return [end]
    return list(range(start, end + 1))


def _source_url(index: str) -> str:
    if index == "ftse250":
        return FTSE250_HISTORY_URL
    return FTSE100_HISTORY_URL


def _preserved_key(name: str) -> str | None:
    from value_investor.ch_failed_name_statements import FAILED_UK_NAMES

    target = normalise_name(name)
    for spec in FAILED_UK_NAMES:
        if normalise_name(spec["name"]) == target:
            return spec["key"]
    return None


def _record_key(name: str, used: set[str]) -> str:
    preserved = _preserved_key(name)
    base = preserved or re.sub(r"[^a-z0-9_]+", "", normalise_name(name).replace(" ", "_"))
    base = base or "unknown"
    key = base
    suffix = 2
    while key in used:
        key = f"{base}_{suffix}"
        suffix += 1
    used.add(key)
    return key


def records_from_leavers(rows: list[dict]) -> list[dict]:
    """Stable leaver records. Company numbers and EPICs are filled later."""
    used: set[str] = set()
    records = []
    for row in rows:
        pdf_name = str(row.get("deleted") or "").replace("*", "").strip()
        name = display_name(pdf_name, str(row.get("notes") or ""))
        leaving = str(row["date"])
        spell = str(row.get("spell_start") or "")
        index = str(row.get("index") or "ftse100")
        records.append(
            {
                "key": _record_key(name, used),
                "name": name,
                "pdf_name": pdf_name,
                "epic": None,
                "epic_source": None,
                "leaving_date": leaving,
                "leaving_date_precision": "day",
                "index": index,
                "reason_class": row["reason_class"],
                "reason": str(row.get("notes") or ""),
                "source_url": _source_url(index),
                "source_page": row.get("page"),
                "spell_start": spell or None,
                "first_year_in_window": first_year_in_window(spell),
                "leaving_year": int(leaving[:4]),
                "expected_years": expected_years(spell, leaving),
                "ch_applicable": None,
                "company_number": None,
                "company_number_status": None,
                "company_number_reason": None,
                "wikipedia_url": None,
                "omitted_from_index_table": bool(row.get("omitted_from_index_table")),
            }
        )
    return records


def _wiki_get(url: str) -> dict:
    import urllib.request

    req = urllib.request.Request(
        url, headers={"User-Agent": "value-investor/0.1 (research; local)"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


_EPIC_RES = (
    re.compile(r"\{\{(?:LSE|London Stock Exchange)\|([A-Z0-9.]{1,6})\}\}", re.I),
    re.compile(r"\bLSE\s*:\s*([A-Z][A-Z0-9.]{1,5})\b"),
    re.compile(r"\[\[London Stock Exchange\|LSE\]\]:\s*([A-Z][A-Z0-9.]{1,5})"),
)


def _epic_in_text(text: str) -> str | None:
    for pattern in _EPIC_RES:
        match = pattern.search(text or "")
        if match:
            return match.group(1).upper().strip(".")
    return None


def _resolve_wiki_title(title: str) -> str | None:
    import urllib.parse

    query = urllib.parse.urlencode(
        {"action": "query", "titles": title, "redirects": 1, "format": "json"}
    )
    payload = _wiki_get(f"https://en.wikipedia.org/w/api.php?{query}")
    pages = (payload.get("query") or {}).get("pages") or {}
    page = next(iter(pages.values()), {})
    if not page or "missing" in page or not page.get("title"):
        return None
    return str(page["title"])


def _candidate_titles(name: str) -> list[str]:
    titles: list[str] = []
    for candidate in (f"{name} Group", f"{name} plc", f"{name} (company)", name):
        try:
            resolved = _resolve_wiki_title(candidate)
        except Exception:
            resolved = None
        if resolved and resolved not in titles:
            titles.append(resolved)
    if titles:
        return titles
    import urllib.parse

    query = urllib.parse.urlencode(
        {
            "action": "query",
            "list": "search",
            "srsearch": f"{name} plc",
            "srlimit": 1,
            "format": "json",
        }
    )
    try:
        found = _wiki_get(f"https://en.wikipedia.org/w/api.php?{query}")
    except Exception:
        return []
    hits = (found.get("query") or {}).get("search") or []
    title = str(hits[0].get("title") or "") if hits else ""
    return [title] if title else []


def _wiki_text(title: str, *, revision_start: str | None = None) -> str:
    import urllib.parse

    if revision_start:
        query = urllib.parse.urlencode(
            {
                "action": "query",
                "titles": title,
                "prop": "revisions",
                "rvstart": revision_start,
                "rvdir": "newer",
                "rvlimit": 1,
                "rvprop": "content",
                "rvslots": "main",
                "redirects": 1,
                "format": "json",
            }
        )
        payload = _wiki_get(f"https://en.wikipedia.org/w/api.php?{query}")
        pages = (payload.get("query") or {}).get("pages") or {}
        page = next(iter(pages.values()), {})
        revs = page.get("revisions") or []
        if not revs:
            return ""
        slot = (revs[0].get("slots") or {}).get("main") or {}
        return str(slot.get("*") or slot.get("content") or "")
    query = urllib.parse.urlencode(
        {"action": "parse", "page": title, "prop": "wikitext", "format": "json"}
    )
    parsed = _wiki_get(f"https://en.wikipedia.org/w/api.php?{query}")
    return str(((parsed.get("parse") or {}).get("wikitext") or {}).get("*") or "")


def wikipedia_epic(name: str, leaving_date: str = "2018-01-01") -> dict[str, str | None]:
    """LSE EPIC from a Wikipedia infobox, including a pre-delisting revision.

    Current pages of taken-over companies often have an empty ``traded_as``. A
    missing ticker stays unresolved. Nothing is guessed from the company name.
    """
    import urllib.parse

    empty = {"epic": None, "epic_source": None, "wikipedia_url": None, "incorporation": None}
    titles = _candidate_titles(name)
    if not titles:
        return empty
    year = max(2008, int(leaving_date[:4]) - 1)
    fallback_url = None
    fallback_text = ""
    for title in titles:
        page_url = "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
        try:
            current = _wiki_text(title)
        except Exception:
            current = ""
        epic = _epic_in_text(current)
        older = ""
        if not epic:
            try:
                older = _wiki_text(title, revision_start=f"{year}-01-01T00:00:00Z")
            except Exception:
                older = ""
            epic = _epic_in_text(older)
        text_for_place = current or older
        if fallback_url is None and text_for_place:
            fallback_url = page_url
            fallback_text = text_for_place
        if not epic:
            continue
        text_for_place = older or current
        non_uk = _NON_UK_RE.search(text_for_place or "")
        incorporation = (
            next((group for group in non_uk.groups() if group), None) if non_uk else None
        )
        if not incorporation:
            adjective = _ADJ_PLACE_RE.search(text_for_place or "")
            if adjective:
                incorporation = _ADJ_PLACE.get(adjective.group(1).lower())
        source = page_url if _epic_in_text(current) else f"{page_url}?oldid_date={year}"
        return {
            "epic": epic,
            "epic_source": source,
            "wikipedia_url": page_url,
            "incorporation": incorporation,
        }
    non_uk = _NON_UK_RE.search(fallback_text or "")
    incorporation = next((group for group in non_uk.groups() if group), None) if non_uk else None
    if not incorporation:
        adjective = _ADJ_PLACE_RE.search(fallback_text or "")
        if adjective:
            incorporation = _ADJ_PLACE.get(adjective.group(1).lower())
    return {
        "epic": None,
        "epic_source": None,
        "wikipedia_url": fallback_url,
        "incorporation": incorporation,
    }


_OVERSEAS_NUMBER_PREFIXES = ("BR", "FC", "NF", "SF", "OE", "OC", "SO", "NC", "IP", "SP", "SL")
_PLC_RE = re.compile(r"\bplc\b|p\s*\.?\s*l\s*\.?\s*c\b|public limited company", re.I)


def is_uk_listed_plc(profile: dict) -> bool:
    """True when this Companies House record is, or was, a UK public limited company.

    A UK subsidiary limited company, and an overseas FC/BR registration, are not
    the listed issuer. A plc that later converted to a private company still
    counts when a current or previous name contains PLC.
    """
    number = str(profile.get("company_number") or "").upper()
    if number.startswith(_OVERSEAS_NUMBER_PREFIXES):
        return False
    jurisdiction = str(profile.get("jurisdiction") or "").lower()
    if jurisdiction and jurisdiction not in UK_JURISDICTIONS:
        return False
    company_type = str(profile.get("type") or "").lower().replace("_", "-")
    if company_type in {"plc", "public-limited-company"}:
        return True
    return any(_PLC_RE.search(name) for name in _ch_names(profile))


def _ch_names(profile: dict) -> list[str]:
    names = [str(profile.get("company_name") or "")]
    for row in profile.get("previous_company_names") or []:
        if isinstance(row, dict) and row.get("name"):
            names.append(str(row["name"]))
    return [name for name in names if name]


def _has_group_accounts(company_number: str, api_key: str, leaving_year: int) -> tuple[bool, str]:
    import time
    import urllib.parse

    from value_investor.research.companies_house import CH_API_BASE, RATE_LIMIT_SLEEP_S, _ch_get

    url = (
        f"{CH_API_BASE}/company/{urllib.parse.quote(company_number)}/filing-history?"
        + urllib.parse.urlencode({"category": "accounts", "items_per_page": 100})
    )
    payload = json.loads(_ch_get(url, api_key=api_key).decode("utf-8"))
    time.sleep(RATE_LIMIT_SLEEP_S)
    group_years: list[str] = []
    other_years: list[str] = []
    for item in payload.get("items") or []:
        if str(item.get("type") or "") != "AA":
            continue
        made = str((item.get("description_values") or {}).get("made_up_date") or "")
        if not made or made < "2012-01-01" or int(made[:4]) > leaving_year:
            continue
        description = str(item.get("description") or "")
        if "group" in description or "accounts-type-group" in description:
            group_years.append(made[:4])
        elif "dormant" not in description and "micro" not in description:
            other_years.append(made[:4])
    if group_years:
        return True, "group AA for " + ", ".join(sorted(set(group_years)))
    if other_years:
        return True, "AA filings (not labelled group) for " + ", ".join(sorted(set(other_years)))
    return False, "no AA filings in 2012..leaving year"


def search_names(record: dict) -> list[str]:
    """Listed name, plus a parenthetical swap, a trust expansion, and a longer note name.

    "Smith (DS)" is also searched as "DS Smith". "Witan Inv Tst" is also searched
    as "Witan Investment Trust". A note that says "offer for Morrison (Wm)
    Supermarkets" is searched as that longer name. The longest name is first.
    """
    name = str(record.get("name") or "")
    found = [name]
    swapped = re.fullmatch(r"(.+?) \(([A-Za-z0-9.&-]+)\)$", name)
    if swapped:
        found.append(f"{swapped.group(2)} {swapped.group(1)}".strip())
    if name.endswith(" Inv Tst"):
        found.append(name[: -len(" Inv Tst")] + " Investment Trust")
    for suffix in (" GBP", " USD", " EUR"):
        if name.endswith(suffix):
            found.append(name[: -len(suffix)].strip())
    note = str(record.get("reason") or "")
    for pattern in (
        r"offer for ([A-Z][^.]{0,80}?) by",
        r"acquisition of ([A-Z][^.]{0,80}?) by",
        r"combination between ([A-Z][^.]{0,80}?) and",
    ):
        match = re.search(pattern, note)
        if match:
            phrase = re.sub(r"\s+", " ", match.group(1)).strip(" -")
            if names_match(name, phrase):
                found.append(phrase)
    expanded = []
    for item in found:
        moved = re.sub(
            r"^(\S+(?: \S+)*) \(([A-Za-z0-9.&-]+)\)\s*",
            r"\2 \1 ",
            item,
        )
        moved = re.sub(r"\s+", " ", moved).strip()
        if moved and moved != item:
            expanded.append(moved)
    found.extend(expanded)
    unique: list[str] = []
    for item in found:
        if item and item not in unique:
            unique.append(item)
    rest = [item for item in unique if item != name]
    rest.sort(key=len, reverse=True)
    return rest + ([name] if name else [])


def _recent_group(detail: str, leaving_year: int) -> bool:
    if not str(detail).startswith("group AA"):
        return False
    years = {int(year) for year in re.findall(r"\d{4}", detail)}
    return leaving_year in years or (leaving_year - 1) in years


def epic_supports_name(name: str, wikipedia_url: str | None) -> bool:
    """False when the Wikipedia page is a different company (Rank for Betfair)."""
    if not wikipedia_url or "/wiki/" not in wikipedia_url:
        return False
    import urllib.parse

    title = urllib.parse.unquote(wikipedia_url.split("/wiki/", 1)[1].split("?", 1)[0])
    title = title.replace("_", " ")
    drop = GENERIC | {"group", "holdings", "holding", "reit", "trust", "fund", "limited"}
    left = {token for token in normalise_name(name).split() if token not in drop}
    right = {token for token in normalise_name(title).split() if token not in drop}
    if not left or not right:
        return True
    return bool(left & right)


def resolve_company_number(record: dict, api_key: str) -> dict:
    """Search Companies House. Never guess when the name or the accounts do not match."""
    import time
    import urllib.parse

    from value_investor.research.companies_house import CH_API_BASE, RATE_LIMIT_SLEEP_S, _ch_get

    if "_search_name" not in record:
        alternates = search_names(record)
        if len(alternates) > 1:
            last = None
            for alternate in alternates:
                trial = {**record, "_search_name": alternate}
                result = resolve_company_number(trial, api_key)
                result["name"] = record["name"]
                if result.get("company_number_status") in {"resolved", "not_applicable"}:
                    return result
                last = result
            return last or record
    name = str(record.get("_search_name") or record["name"])
    # The Group query comes first so a renamed issuer (Aegis Group -> Dentsu)
    # is profiled. A bare "Name PLC" search is full of unrelated limited companies
    # and would otherwise crowd the renamed plc out of the profile cap.
    queries = [f"{name} PLC"]
    if "group" not in name.lower():
        queries.insert(0, f"{name} Group PLC")
    seen: set[str] = set()
    candidates: list[dict] = []
    for query in queries:
        url = f"{CH_API_BASE}/search/companies?" + urllib.parse.urlencode(
            {"q": query, "items_per_page": 10}
        )
        try:
            payload = json.loads(_ch_get(url, api_key=api_key).decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            return {
                **record,
                "ch_applicable": None,
                "company_number_status": "unresolved",
                "company_number_reason": f"Companies House search failed: {exc}",
            }
        time.sleep(RATE_LIMIT_SLEEP_S)
        kept = 0
        for item in payload.get("items") or []:
            number = str(item.get("company_number") or "").strip()
            if not number or number in seen:
                continue
            seen.add(number)
            candidates.append(item)
            kept += 1
            if kept >= 5:
                break
    matched: list[tuple[dict, dict, str]] = []
    for item in candidates:
        number = str(item["company_number"])
        url = f"{CH_API_BASE}/company/{urllib.parse.quote(number)}"
        try:
            profile = json.loads(_ch_get(url, api_key=api_key).decode("utf-8"))
        except Exception:
            time.sleep(RATE_LIMIT_SLEEP_S)
            continue
        time.sleep(RATE_LIMIT_SLEEP_S)
        names = _ch_names(profile)
        if not is_uk_listed_plc(profile):
            continue
        if not any(names_match(name, candidate) for candidate in names):
            continue
        ok, detail = _has_group_accounts(number, api_key, int(record["leaving_year"]))
        if not ok:
            continue
        matched.append((item, profile, detail))
    if len(matched) > 1:
        scored: list[tuple[int, tuple]] = []
        for row in matched:
            extras = [
                extra
                for extra in (_extra_tokens(name, candidate) for candidate in _ch_names(row[1]))
                if extra is not None
            ]
            if extras:
                scored.append((min(extras), row))
        scored.sort(key=lambda item: item[0])
        closest = [row for extra, row in scored if extra == scored[0][0]] if scored else []
        if len(closest) == 1:
            matched = closest
        else:
            recent = [
                row
                for row in (closest or matched)
                if _recent_group(row[2], int(record["leaving_year"]))
            ]
            if len(recent) == 1:
                matched = recent
            else:
                names = ", ".join(
                    str(row[1].get("company_name")) for row in (recent or closest or matched)
                )
                return {
                    **record,
                    "ch_applicable": None,
                    "company_number_status": "unresolved",
                    "company_number_reason": (
                        "More than one UK plc matched the listed name and had accounts "
                        f"in the window: {names}"
                    ),
                }
    if len(matched) == 1:
        _item, profile, detail = matched[0]
        number = str(profile.get("company_number") or "")
        shown = ", ".join(_ch_names(profile)[:4])
        return {
            **record,
            "ch_applicable": True,
            "company_number": number,
            "company_number_status": "resolved",
            "company_number_reason": (
                f"Companies House {number} ({profile.get('company_name')}; "
                f"previous names considered: {shown}). {detail}."
            ),
        }
    incorporation = record.get("incorporation")
    if incorporation:
        return {
            **record,
            "ch_applicable": False,
            "company_number_status": "not_applicable",
            "company_number_reason": (
                f"No UK Companies House entity with matching name and AA filings. "
                f"Wikipedia describes the issuer as incorporated in {incorporation}."
            ),
        }
    return {
        **record,
        "ch_applicable": None,
        "company_number_status": "unresolved",
        "company_number_reason": (
            "Companies House search returned no entity whose current or previous name "
            "matches the listed company and whose AA filings cover the window."
        ),
    }


def _extra_tokens(listed: str, ch_name: str) -> int | None:
    """How many tokens the Companies House name adds beyond the listed name."""
    if not names_match(listed, ch_name):
        return None
    left = set(normalise_name(listed).split())
    right = set(normalise_name(ch_name).split())
    return len(right - left)


def names_match(listed: str, ch_name: str) -> bool:
    """Every distinctive token of the listed name has to appear in the CH name.

    Short tokens (AZ, GKN, Sky) must be whole words, so Sky does not match
    Skyscanner and AZ Electronic Materials does not match every materials company.
    """
    left = [
        token for token in words(listed).split() if token not in GENERIC and not token.isdigit()
    ]
    right_tokens = words(ch_name).split()
    if not left or not right_tokens:
        return False
    right_text = " ".join(right_tokens)
    for token in left:
        if len(token) <= 3:
            if not re.search(rf"\b{re.escape(token)}\b", right_text):
                return False
        elif not _token_in_note(token, right_tokens):
            return False
    return True


def coverage_counts(records: list[dict]) -> dict:
    from collections import Counter

    counts = Counter(row["reason_class"] for row in records)
    applicable = Counter(row["reason_class"] for row in records if row.get("ch_applicable") is True)
    not_applicable = sum(1 for row in records if row.get("ch_applicable") is False)
    unresolved = sum(1 for row in records if row.get("company_number_status") == "unresolved")
    return {
        "names": len(records),
        "by_reason_class": {
            "takeover": counts.get("takeover", 0),
            "failure": counts.get("failure", 0),
            "other": counts.get("other", 0),
        },
        "ch_applicable": sum(applicable.values()),
        "ch_applicable_by_reason_class": {
            "takeover": applicable.get("takeover", 0),
            "failure": applicable.get("failure", 0),
            "other": applicable.get("other", 0),
        },
        "ch_not_applicable": not_applicable,
        "unresolved": unresolved,
    }


def build_payload(records: list[dict], *, generated_at: str) -> dict:
    counts = coverage_counts(records)
    return {
        "schema_version": 1,
        "generated_at": generated_at,
        "window": {"from": WINDOW_START.isoformat(), "to": WINDOW_END.isoformat()},
        "learning_question": (
            "Which FTSE 350 names left by delisting between 2013-01-01 and 2025-09-30, "
            "and for which of those can Companies House supply point-in-time annual statements?"
        ),
        "method": (
            "FTSE Russell historic addition and deletion logs (October 2026 PDFs) parsed by "
            "column. A row is a leaver when the note names that company as acquired, failed, "
            "or moved off the eligible London listing, and the name is not back in either "
            "index within 7 days. Empty-note quarterly deletions are demotions or promotions "
            "and are excluded. Wikipedia FTSE 100 past constituents were used as a cross-check, "
            "not as the date source. SABMiller is taken from the FTSE 250 note that records "
            "the FTSE 100 acquisition, because that row is absent from the FTSE 100 PDF."
        ),
        "completeness": (
            f"{counts['names']} delisting exits. The Russell change log is the full official "
            "history through October 2026, so labelled takeovers, schemes, suspensions and "
            "listing transfers in the window should be present. Demotions of companies that "
            "stayed listed are excluded on purpose, which is why the count is not every name "
            "that ever left the index. Residual gaps are an omitted PDF row (SABMiller, "
            "recovered from the other index's note) and a failure deleted at a quarterly "
            "review with no note. Estimate: within about 10% of the delisting set."
        ),
        "sources": [
            {"id": "ftse100_history", "url": FTSE100_HISTORY_URL, "retrieved": "2026-11-12"},
            {"id": "ftse250_history", "url": FTSE250_HISTORY_URL, "retrieved": "2026-11-12"},
            {
                "id": "wikipedia_ftse100_past_constituents",
                "url": WIKIPEDIA_PAST_CONSTITUENTS_URL,
                "retrieved": "2026-11-12",
            },
        ],
        "counts": counts,
        "licence": (
            "Index dates are from FTSE Russell historic constituent change logs. "
            "Companies House numbers and accounts, where present, are Crown copyright "
            "and reused under the Open Government Licence v3.0."
        ),
        "names": records,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    from datetime import UTC, datetime
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Build the FTSE 350 delisting leaver list.")
    parser.add_argument("--ftse100-pdf", type=Path, default=Path("/tmp/ftse-hist/ftse100.pdf"))
    parser.add_argument("--ftse250-pdf", type=Path, default=Path("/tmp/ftse-hist/ftse250.pdf"))
    parser.add_argument(
        "--out", type=Path, default=Path("docs/data/ftse350_leavers_2013_2025.json")
    )
    parser.add_argument("--resolve-epic", action="store_true")
    parser.add_argument("--resolve-ch", action="store_true")
    parser.add_argument("--cache-dir", type=Path, default=Path("/tmp/ftse-leaver-resolve"))
    args = parser.parse_args(argv)
    events = parse_history_pdf(str(args.ftse100_pdf), "ftse100") + parse_history_pdf(
        str(args.ftse250_pdf), "ftse250"
    )
    leavers, _diag = select_leavers(events)
    records = records_from_leavers(leavers)
    args.cache_dir.mkdir(parents=True, exist_ok=True)

    def checkpoint() -> None:
        payload = build_payload(
            records, generated_at=datetime.now(UTC).replace(microsecond=0).isoformat()
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    api_key = None
    if args.resolve_ch:
        from value_investor.research.companies_house import companies_house_api_key

        api_key = companies_house_api_key()
        if not api_key:
            print("COMPANIES_HOUSE_API_KEY is not set")
            return 2
    if args.resolve_epic or args.resolve_ch:
        for index, record in enumerate(records, start=1):
            cache_path = args.cache_dir / f"{record['key']}.json"
            if cache_path.exists():
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                record.clear()
                record.update(cached)
                if record.get("wikipedia_url") and not epic_supports_name(
                    record["name"], record.get("wikipedia_url")
                ):
                    record["epic"] = None
                    record["epic_source"] = None
                    record["wikipedia_url"] = None
                if isinstance(record.get("epic"), str):
                    record["epic"] = record["epic"].strip(".") or None
                continue
            if args.resolve_epic:
                wiki = wikipedia_epic(record["name"], record["leaving_date"])
                record["epic"] = wiki["epic"]
                record["epic_source"] = wiki["epic_source"]
                record["wikipedia_url"] = wiki["wikipedia_url"]
                record["incorporation"] = wiki["incorporation"]
            if record.get("wikipedia_url") and not epic_supports_name(
                record["name"], record.get("wikipedia_url")
            ):
                record["epic"] = None
                record["epic_source"] = None
                record["wikipedia_url"] = None
            if isinstance(record.get("epic"), str):
                record["epic"] = record["epic"].strip(".") or None
            if args.resolve_ch and api_key:
                updated = resolve_company_number(record, api_key)
                record.clear()
                record.update(updated)
            cache_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
            print(
                f"{index}/{len(records)} {record['name']} epic={record.get('epic')} "
                f"ch={record.get('company_number_status')} {record.get('company_number')}",
                flush=True,
            )
            if index % 10 == 0:
                checkpoint()
    payload = build_payload(
        records, generated_at=datetime.now(UTC).replace(microsecond=0).isoformat()
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        "wrote",
        args.out,
        "names",
        payload["counts"]["names"],
        payload["counts"]["by_reason_class"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
