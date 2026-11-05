"""Current-vs-prior half-year revenue and EPS from results filing bodies.

UK issuers report half-yearly. The text already on disk (results RNS and
half-year reports) is the source when a quarterly series has no prior-year
period. Figures are kept only when current and prior are both present, the
prior period is about one year earlier, and the column order is explicit.
Anything ambiguous is left unextracted. The decline gate reads the result; it
does not treat a missing extract as a pass.

See ``docs/ops/operating-decline-gate.md``.
"""

from __future__ import annotations

import calendar
import re
from datetime import date
from typing import Any

# Same tokens the decline gate uses to decide a row is a half-year results body.
HALF_YEAR_RESULTS_TOKENS = (
    "interim results",
    "interim report",
    "half-year",
    "half year",
    "half-yearly",
    "half yearly",
)

# A prior period end more than this many days away from "one year earlier" is rejected.
PRIOR_PERIOD_WINDOW_DAYS = 45

_THIRD_PARTY_PREFIXES = ("google_news",)

_LABEL_RANK = {
    "total group revenue": 0,
    "group revenue": 1,
    "total revenue": 2,
    "turnover": 3,
    "net operating revenue": 4,
    "net revenue": 5,
    "revenue": 6,
}

_SEGMENT_PREFIXES = frozenset(
    {
        "advertising",
        "ad",
        "studios",
        "external",
        "internal",
        "digital",
        "branded",
        "injectables",
        "vending",
        "retail",
        "wholesale",
        "divisional",
        "segment",
        "subscription",
        "organic",
        "lfl",
        "like-for-like",
        "third-party",
        "customer",
        "customers",
        "product",
        "service",
        "services",
        "online",
        "store",
        "stores",
        "division",
        "regional",
        "domestic",
        "international",
        "overseas",
        "discontinued",
        "non-advertising",
    }
)

_REVENUE_LABEL_RE = re.compile(
    r"(?i)(?P<label>total\s+group\s+revenue|group\s+revenue|total\s+revenue|"
    r"net\s+operating\s+revenue|net\s+revenue|turnover|revenue)\d{0,2}"
    r"(?!\d)(?!\s+and\s+other\b)"
)

_EPS_LABEL_RE = re.compile(
    r"(?ix)(?P<label>"
    r"adjusted\s+diluted\s+(?:earnings\s+per\s+share|eps)"
    r"|adjusted\s+basic\s+(?:earnings\s+per\s+share|eps)"
    r"|diluted\s+adjusted\s+(?:earnings\s+per\s+share|eps)"
    r"|basic\s+adjusted\s+(?:earnings\s+per\s+share|eps)"
    r"|diluted\s+(?:earnings\s+per\s+share|eps)"
    r"|basic\s+(?:earnings\s+per\s+share|eps)"
    r"|adjusted\s+(?:earnings\s+per\s+share|eps)"
    r"|statutory\s+(?:earnings\s+per\s+share|eps)"
    r"|underlying\s+(?:diluted\s+|basic\s+)?(?:earnings\s+per\s+share|eps)"
    r"|core\s+(?:diluted\s+|basic\s+)?(?:earnings\s+per\s+share|eps)"
    r"|(?:earnings\s+per\s+share|eps)\s*\(\s*(?:diluted|basic|adjusted)\s*\)"
    r"|earnings\s+per\s+share"
    r"|eps"
    r")\d{0,2}(?!\d)"
)

_PERIOD_RE = re.compile(
    r"(?ix)(?:(?P<weeks>\d{1,2})\s+weeks?|(?:six|6)\s+months?|half[-\s]?year)"
    r"\s+(?:ended|ending|to)\s+"
    r"(?P<day>\d{1,2})(?:st|nd|rd|th)?\s+(?P<mon>[A-Za-z]+)\s+(?P<year>20\d{2})"
)

_HEADER_YEAR_RE = re.compile(
    r"(?ix)"
    r"(?:(?P<h1>H1|HY|1H)\s*(?:FY\s*)?(?P<h1year>(?:20)?\d{2}))"
    r"|(?:(?:ended|ending|to)\s+\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+(?P<endyear>20\d{2}))"
    r"|(?:(?P<bare>20\d{2}))"
)

_AMOUNT_RE = re.compile(
    r"(?ix)(?P<neg>\()?\s*(?P<cur>US\$|£|\$|€)?\s*"
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*"
    r"(?P<unit>billions?|millions?|bn|pence|cents|cts|m|p)?\s*\)?"
)

_UNIT = r"(?:billions?|millions?|bn|pence|cents|cts|m|p)"
_CUR = r"(?:US\$|£|\$|€)"
# A decimal in "3.9%" is not the end of a sentence. A period before a space is.
_MID = r"(?:(?!\.\s)[^\n])"

_PROSE_CURRENT_FROM = re.compile(
    rf"(?ix)(?P<cur>{_CUR})\s*(?P<cnum>\d[\d,]*(?:\.\d+)?)\s*"
    rf"(?P<cunit>{_UNIT})?(?!\s*%)"
    rf"(?P<mid>{_MID}{{0,70}}?)\bfrom\s+"
    rf"(?P<prior>{_CUR})?\s*(?P<pnum>\d[\d,]*(?:\.\d+)?)\s*"
    rf"(?P<punit>{_UNIT})?(?!\s*%)"
)

_PROSE_UNIT_FROM = re.compile(
    rf"(?ix)(?P<cnum>\d[\d,]*(?:\.\d+)?)\s*(?P<cunit>pence|cents|cts|p)(?!\s*%)"
    rf"(?P<mid>{_MID}{{0,50}}?)\bfrom\s+"
    rf"(?P<pnum>\d[\d,]*(?:\.\d+)?)\s*(?P<punit>pence|cents|cts|p)(?!\s*%)"
)

_PROSE_FROM_TO = re.compile(
    rf"(?ix)\bfrom\s+(?P<prior>{_CUR})?\s*(?P<pnum>\d[\d,]*(?:\.\d+)?)\s*"
    rf"(?P<punit>{_UNIT})?(?!\s*%)\s+"
    rf"to\s+(?P<cur>{_CUR})?\s*(?P<cnum>\d[\d,]*(?:\.\d+)?)\s*"
    rf"(?P<cunit>{_UNIT})?(?!\s*%)"
)

_PROSE_PAREN = re.compile(
    rf"(?ix)(?P<cur>{_CUR})?\s*(?P<cnum>\d[\d,]*(?:\.\d+)?)\s*"
    rf"(?P<cunit>{_UNIT})?(?!\s*%)"
    rf"(?P<mid>{_MID}{{0,80}}?)"
    rf"\(\s*(?:H1|HY|FY)?\s*(?P<year>20\d{{2}})\s*[:\-–]\s*"
    rf"(?P<prior>{_CUR})?\s*(?P<pnum>\d[\d,]*(?:\.\d+)?)\s*"
    rf"(?P<punit>{_UNIT})?(?!\s*%)"
)


def is_half_year_results_row(row: dict[str, Any]) -> bool:
    """True for a dated interim results / half-year report row that has a body."""
    if not isinstance(row, dict):
        return False
    if str(row.get("source") or "").startswith(_THIRD_PARTY_PREFIXES):
        return False
    if str(row.get("period") or "") != "interim" or not row.get("has_body"):
        return False
    blob = f"{row.get('headline') or ''} {row.get('url') or ''}".lower()
    return any(token in blob for token in HALF_YEAR_RESULTS_TOKENS)


def about_one_year(current: date, prior: date) -> bool:
    """True when ``prior`` is the same point a year before ``current``, within 45 days."""
    if prior >= current:
        return False
    try:
        target = current.replace(year=current.year - 1)
    except ValueError:
        target = current.replace(year=current.year - 1, day=28)
    return abs((prior - target).days) <= PRIOR_PERIOD_WINDOW_DAYS


def parse_half_year_results(body_text: str) -> dict[str, Any]:
    """Extract one current-vs-prior half from a results body.

    ``status`` is ``extracted`` only when a period pair about one year apart is
    known and at least one of revenue or EPS has both figures. Revenue must be
    positive. Column order that is not explicit is not extracted.
    """
    blank = _blank_result()
    if not body_text or not str(body_text).strip():
        blank["why"] = "empty_body"
        return blank
    text = _clean(str(body_text))
    current_end, prior_end, prior_basis = _period_pair(text)
    if current_end is None:
        blank["why"] = "period_end_missing"
        return blank
    revenue, revenue_why = _best_revenue(text)
    eps_rows, eps_why = _best_eps(text)
    if prior_end is None and (revenue is not None or eps_rows):
        prior_end = _shift_year(current_end, -1)
        prior_basis = "inferred"
    if prior_end is None or not about_one_year(current_end, prior_end):
        blank["why"] = "prior_period_not_one_year"
        blank["period_end"] = current_end.isoformat()
        return blank
    if revenue is None and not eps_rows:
        blank["why"] = revenue_why or eps_why or "figures_not_found"
        blank["period_end"] = current_end.isoformat()
        blank["prior_period_end"] = prior_end.isoformat()
        return blank
    if revenue is not None and (revenue["current"] <= 0 or revenue["prior"] <= 0):
        revenue = None
        revenue_why = "revenue_non_positive"
    if revenue is None and not eps_rows:
        blank["why"] = revenue_why or "figures_not_found"
        blank["period_end"] = current_end.isoformat()
        blank["prior_period_end"] = prior_end.isoformat()
        return blank
    confidence = "medium" if prior_basis == "inferred" else "high"
    return {
        "status": "extracted",
        "why": None,
        "period_end": current_end.isoformat(),
        "prior_period_end": prior_end.isoformat(),
        "prior_period_basis": prior_basis,
        "revenue": revenue,
        "eps": eps_rows,
        "parse_confidence": confidence,
        "revenue_why": None if revenue else revenue_why,
        "eps_why": None if eps_rows else eps_why,
    }


def _blank_result() -> dict[str, Any]:
    return {
        "status": "not_extracted",
        "why": "figures_not_found",
        "period_end": None,
        "prior_period_end": None,
        "prior_period_basis": None,
        "revenue": None,
        "eps": [],
        "parse_confidence": None,
        "revenue_why": None,
        "eps_why": None,
    }


def _clean(text: str) -> str:
    return (
        text.replace("\u00a0", " ")
        .replace("\u202f", " ")
        .replace("\u2009", " ")
        .replace("–", "-")
        .replace("—", "-")
    )


def _month_number(name: str) -> int | None:
    key = name.strip().lower()
    for index, full in enumerate(calendar.month_name):
        if full and full.lower() == key:
            return index
    for index, abbr in enumerate(calendar.month_abbr):
        if abbr and abbr.lower() == key:
            return index
    return None


def _parse_date(day: str, month: str, year: str) -> date | None:
    month_number = _month_number(month)
    if month_number is None:
        return None
    try:
        return date(int(year), month_number, int(day))
    except ValueError:
        return None


def _shift_year(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:
        return day.replace(year=day.year + years, day=28)


def _period_pair(text: str) -> tuple[date | None, date | None, str | None]:
    found: list[date] = []
    for match in _PERIOD_RE.finditer(text):
        weeks = match.group("weeks")
        if weeks and int(weeks) >= 40:
            continue
        parsed = _parse_date(match.group("day"), match.group("mon"), match.group("year"))
        if parsed is not None:
            found.append(parsed)
    if not found:
        return None, None, None
    current = max(found)
    prior_candidates = [item for item in found if about_one_year(current, item)]
    if not prior_candidates:
        return current, None, None
    try:
        target = current.replace(year=current.year - 1)
    except ValueError:
        target = current.replace(year=current.year - 1, day=28)
    prior = min(prior_candidates, key=lambda item: abs((item - target).days))
    return current, prior, "stated"


def _normalise_label(label: str) -> str:
    return re.sub(r"\s+", " ", label).strip().lower()


def _preceding_word(text: str, start: int) -> str:
    prefix = text[max(0, start - 40) : start]
    match = re.search(r"([A-Za-z0-9&][A-Za-z0-9&.'-]*)\s*$", prefix)
    return match.group(1).lower() if match else ""


def _segment_prefixed(text: str, start: int) -> bool:
    word = _preceding_word(text, start)
    if not word:
        return False
    if "&" in word or word in _SEGMENT_PREFIXES:
        return True
    return False


def _snippet(text: str, start: int, end: int) -> str:
    raw = text[max(0, start - 20) : min(len(text), end + 80)]
    collapsed = re.sub(r"\s+", " ", raw).strip()
    if len(collapsed) > 220:
        collapsed = collapsed[:217].rstrip() + "..."
    return collapsed


def _year_from_token(match: re.Match[str]) -> int | None:
    if match.group("h1year"):
        year = int(match.group("h1year"))
        return year + 2000 if year < 100 else year
    if match.group("endyear"):
        return int(match.group("endyear"))
    bare = match.group("bare")
    if not bare:
        return None
    window = match.string[max(0, match.start() - 24) : match.end() + 24]
    if re.search(r"(?i)£\s*m|\$\s*m|€\s*m|us\$|pence|\(p\)|\bchange\b|\bvariance\b", window):
        return int(bare)
    return None


def _column_order(text: str, label_pos: int) -> dict[str, Any] | None:
    """Year-column order for the table header that introduces this row.

    Returns None when the header is missing or the order is ambiguous (mixed
    quarters, or the first two period years are not one year apart).
    """
    window = text[max(0, label_pos - 1000) : label_pos]
    near = window[-350:]
    if re.search(r"(?i)\bQ[1-4]\b", near) and re.search(
        r"(?i)\bhalf|\bH1\b|\bHY\b|six months", near
    ):
        return None
    tokens: list[tuple[int, int]] = []
    for match in _HEADER_YEAR_RE.finditer(window):
        year = _year_from_token(match)
        if year is None or not 1990 <= year <= 2100:
            continue
        if tokens and tokens[-1][1] == year and match.start() - tokens[-1][0] < 8:
            continue
        tokens.append((match.start(), year))
    # The header that belongs to this row is the last year-pair before the label.
    pair_index = None
    for index in range(len(tokens) - 1):
        if abs(tokens[index][1] - tokens[index + 1][1]) != 1:
            continue
        if tokens[index + 1][0] - tokens[index][0] > 180:
            continue
        pair_index = index
    if pair_index is None:
        return None
    first, second = tokens[pair_index][1], tokens[pair_index + 1][1]
    repeated = False
    if pair_index + 3 < len(tokens):
        third, fourth = tokens[pair_index + 2][1], tokens[pair_index + 3][1]
        gap = tokens[pair_index + 2][0] - tokens[pair_index + 1][0]
        if third == first and fourth == second and gap < 180:
            repeated = True
    change = bool(re.search(r"(?i)\b(?:change|variance|yoy|y/y|vs\.?)\b|%", window[-220:]))
    return {
        "order": "current_first" if first > second else "prior_first",
        "repeated": repeated,
        "change": change,
    }


def _parse_number(raw: str, *, negative: bool) -> float | None:
    try:
        value = float(raw.replace(",", ""))
    except ValueError:
        return None
    if negative:
        value = -abs(value)
    return value


def _unit_name(raw: str | None, *, kind: str) -> str | None:
    if not raw:
        return None
    token = raw.lower()
    if token in {"p", "pence"}:
        return "pence"
    if token in {"cts", "cents"}:
        return "cents"
    if token in {"bn", "billion", "billions"}:
        return "billions"
    if token in {"m", "million", "millions"}:
        return "millions"
    return None


def _currency_code(symbol: str | None) -> str | None:
    if not symbol:
        return None
    if symbol == "£":
        return "GBP"
    if symbol in {"$", "US$"}:
        return "USD"
    if symbol == "€":
        return "EUR"
    return None


def _amount_dicts(fragment: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for match in _AMOUNT_RE.finditer(fragment):
        tail = fragment[match.end() : match.end() + 3]
        if re.match(r"\s*%", tail):
            continue
        number = _parse_number(match.group("num"), negative=bool(match.group("neg")))
        if number is None:
            continue
        unit = _unit_name(match.group("unit"), kind="money")
        currency = _currency_code(match.group("cur"))
        if unit is None and currency is None and 1990 <= number <= 2100 and number == int(number):
            continue
        found.append(
            {
                "value": number,
                "unit": unit,
                "currency": currency,
                "small_int": unit is None
                and currency is None
                and float(number).is_integer()
                and 0 < number <= 20,
                "eps_unit": unit in {"pence", "cents"},
            }
        )
    return found


def _strip_footnote(amounts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if (
        len(amounts) >= 2
        and amounts[0]["small_int"]
        and (amounts[1]["unit"] or amounts[1]["currency"] or not amounts[1]["small_int"])
    ):
        return amounts[1:]
    if any(item["eps_unit"] for item in amounts):
        kept = [item for item in amounts if item["eps_unit"]]
        return kept or amounts
    return amounts


def _inherit(current: dict[str, Any], prior: dict[str, Any]) -> bool:
    """Fill a missing unit or currency from the other side. False if they conflict."""
    for key in ("unit", "currency"):
        left, right = current.get(key), prior.get(key)
        if left and right and left != right:
            return False
        if left and not right:
            prior[key] = left
        elif right and not left:
            current[key] = right
    return True


def _pair_from_amounts(
    amounts: list[dict[str, Any]], columns: dict[str, Any], *, eps: bool = False
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    amounts = _strip_footnote(amounts)
    if len(amounts) < 2:
        return None
    if columns["repeated"]:
        if len(amounts) < 4:
            pair = amounts[:2]
        else:
            if abs(amounts[0]["value"] - amounts[2]["value"]) > 0.05:
                return None
            if abs(amounts[1]["value"] - amounts[3]["value"]) > 0.05:
                return None
            pair = amounts[:2]
    elif len(amounts) >= 3 and _third_is_another_period(amounts):
        return None
    elif len(amounts) >= 4 and _second_pair_is_another_measure(amounts):
        return None
    elif len(amounts) > 2 and not columns["change"]:
        return None
    else:
        pair = amounts[:2]
    current, prior = pair[0], pair[1]
    if columns["order"] == "prior_first":
        current, prior = prior, current
    # Bare 1 and 2 are note numbers ("Customers 1 to 2"), not a revenue row.
    # Pence and cents are often whole numbers under 20, so EPS keeps them.
    if not eps and (current.get("small_int") or prior.get("small_int")):
        return None
    if not _inherit(current, prior):
        return None
    return current, prior


def _third_is_another_period(amounts: list[dict[str, Any]]) -> bool:
    """A third figure as large as the first two is another period, not a change column."""
    scale = max(abs(amounts[0]["value"]), abs(amounts[1]["value"]), 0.01)
    return abs(amounts[2]["value"]) > scale * 0.5


def _second_pair_is_another_measure(amounts: list[dict[str, Any]]) -> bool:
    """True when four similar-sized figures are two measures, not value plus change."""
    scale = max(abs(amounts[0]["value"]), abs(amounts[1]["value"]), 0.01)
    other = max(abs(amounts[2]["value"]), abs(amounts[3]["value"]))
    if other <= scale * 0.25:
        return False
    return (
        abs(amounts[0]["value"] - amounts[2]["value"]) > 0.05
        or abs(amounts[1]["value"] - amounts[3]["value"]) > 0.05
    )


def _fill_eps_currency(current: dict[str, Any], prior: dict[str, Any]) -> None:
    if current.get("currency"):
        prior.setdefault("currency", current["currency"])
        return
    unit = current.get("unit")
    if unit == "pence":
        current["currency"] = prior["currency"] = "GBP"
    elif unit == "cents":
        current["currency"] = prior["currency"] = "USD"
    elif unit == "dollars":
        current["currency"] = prior["currency"] = "USD"


def _header_eps_unit(text: str, label_pos: int) -> str | None:
    window = text[max(0, label_pos - 180) : label_pos + 40]
    if re.search(r"(?i)\bpence\b|\(p\)", window):
        return "pence"
    if re.search(r"(?i)\bcents\b|\bcts\b", window):
        return "cents"
    if re.search(r"\(\$\)", window):
        return "dollars"
    return None


def _header_money_hint(text: str, label_pos: int) -> tuple[str | None, str | None]:
    window = text[max(0, label_pos - 250) : label_pos]
    currency = None
    unit = None
    if re.search(r"£", window):
        currency = "GBP"
    elif re.search(r"(?i)US\$|\$", window):
        currency = "USD"
    elif "€" in window:
        currency = "EUR"
    if re.search(r"(?i)£\s*m|\$\s*m|€\s*m|\bmillion\b", window):
        unit = "millions"
    elif re.search(r"(?i)\bbillion\b|\bbn\b", window):
        unit = "billions"
    return currency, unit


def _apply_header_hint(
    current: dict[str, Any], prior: dict[str, Any], text: str, label_pos: int, *, eps: bool
) -> bool:
    if eps:
        return True
    currency, unit = _header_money_hint(text, label_pos)
    for item in (current, prior):
        # A symbol with no unit (£6,975) is major currency units, not millions.
        # Header millions apply only to bare table numbers.
        if item.get("unit") is None and unit and item.get("currency") is None:
            item["unit"] = unit
        if item.get("currency") is None and currency:
            item["currency"] = currency
    if current.get("unit") != prior.get("unit") or not current.get("unit"):
        return False
    if current.get("currency") != prior.get("currency") or not current.get("currency"):
        return False
    return True


_NEXT_METRIC_RE = re.compile(
    r"(?i)\s+(?:gross|operating|adjusted|statutory|underlying|profit|ebitda|ebit|"
    r"margin|earnings|dividend|capex|like-for-like|revenue|turnover|eps|basic|"
    r"diluted|total\s|group\s|net\s)\b"
)


def _row_rest(text: str, label_end: int) -> str:
    """The figures on this row only, not the next metric's numbers."""
    rest = text[label_end : label_end + 160]
    cut = _NEXT_METRIC_RE.search(rest)
    if cut is not None and cut.start() > 0:
        rest = rest[: cut.start()]
    return rest


def _mid_is_clean(mid: str) -> bool:
    if re.search(r"(?i)\b(?:revenue|profit|earnings|dividend|margin|ebit)\b", mid):
        return False
    if re.search(r"(?:£|\$|€)\s*\d", mid):
        return False
    without_percent = re.sub(r"\d+(?:\.\d+)?\s*%", "", mid)
    if re.search(r"\d", without_percent):
        return False
    return True


def _table_candidate(text: str, match: re.Match[str], *, eps: bool) -> dict[str, Any] | None:
    if _segment_prefixed(text, match.start()):
        return None
    columns = _column_order(text, match.start())
    if columns is None:
        return None
    rest = _row_rest(text, match.end())
    amounts = _amount_dicts(rest)
    paired = _pair_from_amounts(amounts, columns, eps=eps)
    if paired is None:
        return None
    current, prior = paired
    if eps:
        if not current.get("eps_unit"):
            hinted = _header_eps_unit(text, match.start())
            if hinted is None:
                return None
            current["unit"] = prior["unit"] = hinted
            current["eps_unit"] = prior["eps_unit"] = hinted in {"pence", "cents"}
        if not _inherit(current, prior):
            return None
        _fill_eps_currency(current, prior)
        if not current.get("currency"):
            return None
    elif not _apply_header_hint(current, prior, text, match.start(), eps=False):
        return None
    if current["value"] == 0 and prior["value"] == 0:
        return None
    label = _normalise_label(match.group("label"))
    return {
        "label": re.sub(r"\s+", " ", match.group("label")).strip(),
        "label_key": label,
        "current": current["value"],
        "prior": prior["value"],
        "unit": current.get("unit"),
        "currency": current.get("currency"),
        "snippet": _snippet(text, match.start(), match.end() + 80),
        "order_basis": "column_headers",
    }


def _prose_window(text: str, match: re.Match[str]) -> str:
    return text[match.end() : match.end() + 220]


def _prose_pairs(window: str) -> list[tuple[str, dict[str, Any], dict[str, Any], int]]:
    """Explicit current/prior prose. Each item is basis, current, prior, end offset."""
    found: list[tuple[int, str, dict[str, Any], dict[str, Any], int]] = []
    patterns = (
        ("stated_from", _PROSE_CURRENT_FROM),
        ("stated_from", _PROSE_UNIT_FROM),
        ("stated_from", _PROSE_FROM_TO),
        ("prior_year_in_parentheses", _PROSE_PAREN),
    )
    for basis, pattern in patterns:
        hit = None
        for candidate in pattern.finditer(window):
            if candidate.start() > 90:
                break
            if not _mid_is_clean(candidate.groupdict().get("mid") or ""):
                continue
            if re.search(
                r"(?i)\b(?:ebitda|ebit|profit|earnings|dividend|margin|eps)\b",
                window[: candidate.start()],
            ):
                continue
            hit = candidate
            break
        if hit is None:
            continue
        current = {
            "value": _parse_number(hit.group("cnum"), negative=False),
            "unit": _unit_name(hit.group("cunit"), kind="money"),
            "currency": _currency_code(hit.groupdict().get("cur")),
        }
        prior = {
            "value": _parse_number(hit.group("pnum"), negative=False),
            "unit": _unit_name(hit.group("punit"), kind="money"),
            "currency": _currency_code(hit.groupdict().get("prior")),
        }
        if current["value"] is None or prior["value"] is None:
            continue
        if not _inherit(current, prior):
            continue
        if re.match(r"(?i)\s*loss\b", window[hit.end() : hit.end() + 16]):
            prior["value"] = -abs(float(prior["value"]))
        _fill_eps_currency(current, prior)
        found.append((hit.start(), basis, current, prior, hit.end()))
    if not found:
        return []
    found.sort(key=lambda item: item[0])
    _start, basis, current, prior, end = found[0]
    return [(basis, current, prior, end)]


def _candidate_from_prose(text: str, match: re.Match[str], *, eps: bool) -> dict[str, Any] | None:
    if _segment_prefixed(text, match.start()):
        return None
    window = _prose_window(text, match)
    # A segment sentence ("revenue from 4 customers ...") is not a group total.
    if re.search(r"(?i)\b(?:segment|customers?|division)\b", window[:80]):
        return None
    pairs = _prose_pairs(window)
    if not pairs:
        return None
    basis, current, prior, end = pairs[0]
    if eps and current.get("unit") not in {"pence", "cents", "dollars"}:
        return None
    if eps:
        _fill_eps_currency(current, prior)
    elif not _apply_header_hint(current, prior, text, match.start(), eps=False):
        return None
    label = _normalise_label(match.group("label"))
    return {
        "label": re.sub(r"\s+", " ", match.group("label")).strip(),
        "label_key": label,
        "current": current["value"],
        "prior": prior["value"],
        "unit": current.get("unit"),
        "currency": current.get("currency"),
        "snippet": _snippet(text, match.start(), match.end() + end),
        "order_basis": "prior_year_in_parentheses"
        if basis == "prior_year_in_parentheses"
        else "stated_from",
    }


def _values_agree(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if left.get("unit") != right.get("unit") or left.get("currency") != right.get("currency"):
        return False
    for key in ("current", "prior"):
        base = abs(float(right[key])) or 1.0
        if abs(float(left[key]) - float(right[key])) / base > 0.005:
            return False
    return True


def _best_revenue(text: str) -> tuple[dict[str, Any] | None, str | None]:
    candidates: list[dict[str, Any]] = []
    for match in _REVENUE_LABEL_RE.finditer(text):
        for built in (
            _table_candidate(text, match, eps=False),
            _candidate_from_prose(text, match, eps=False),
        ):
            if built is None:
                continue
            if built["label_key"] not in _LABEL_RANK:
                continue
            if built["current"] <= 0 or built["prior"] <= 0:
                continue
            if built.get("unit") not in {"millions", "billions"}:
                continue
            candidates.append(built)
    if not candidates:
        return None, "revenue_not_found"
    best_rank = min(_LABEL_RANK[item["label_key"]] for item in candidates)
    # A group total suppresses segment lines that only matched a weaker label.
    chosen = [item for item in candidates if _LABEL_RANK[item["label_key"]] == best_rank]
    if best_rank <= _LABEL_RANK["total revenue"]:
        chosen = [item for item in candidates if _LABEL_RANK[item["label_key"]] <= best_rank]
        best_rank = min(_LABEL_RANK[item["label_key"]] for item in chosen)
        chosen = [item for item in chosen if _LABEL_RANK[item["label_key"]] == best_rank]
    tables = [item for item in chosen if item.get("order_basis") == "column_headers"]
    if tables:
        chosen = tables
    reference = chosen[0]
    if any(not _values_agree(reference, item) for item in chosen[1:]):
        return None, "revenue_ambiguous"
    reference = dict(reference)
    reference.pop("label_key", None)
    return reference, None


def _eps_kind(label_key: str) -> str | None:
    if label_key in {"eps"}:
        return None
    if any(token in label_key for token in ("adjusted", "underlying", "core")):
        return "adjusted"
    if "diluted" in label_key:
        return "diluted"
    if "basic" in label_key:
        return "basic"
    if "statutory" in label_key:
        return "statutory"
    if "earnings per share" in label_key:
        return "basic"
    return None


def _best_eps(text: str) -> tuple[list[dict[str, Any]], str | None]:
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for match in _EPS_LABEL_RE.finditer(text):
        kind = _eps_kind(_normalise_label(match.group("label")))
        if kind is None:
            continue
        built = _table_candidate(text, match, eps=True) or _candidate_from_prose(
            text, match, eps=True
        )
        if built is None:
            continue
        if built["prior"] <= 0:
            continue
        built["kind"] = kind
        built.pop("label_key", None)
        by_kind.setdefault(kind, []).append(built)
    kept: list[dict[str, Any]] = []
    for kind in ("diluted", "basic", "adjusted", "statutory"):
        rows = by_kind.get(kind) or []
        if not rows:
            continue
        tables = [item for item in rows if item.get("order_basis") == "column_headers"]
        if tables and all(_values_agree(tables[0], item) for item in tables[1:]):
            kept.append(tables[0])
            continue
        if any(not _values_agree(rows[0], item) for item in rows[1:]):
            continue
        kept.append(rows[0])
    if not kept:
        return [], "eps_not_found"
    return kept, None
