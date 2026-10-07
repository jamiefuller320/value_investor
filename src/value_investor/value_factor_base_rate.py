"""Published value-factor base rate (Ken French), not this repository's screen.

Learning question: on a long history that reinvests dividends, what premium
does a published value portfolio earn over the market and over growth, and
how much of that premium is the dividend?

US portfolios are CRSP (delisting returns included). UK country portfolios are
MSCI through 2006 and Bloomberg after that, in local currency, value-weighted.
They are not a replay of ``assign_signal``.

The raw French files are copyright Eugene F. Fama and Kenneth R. French and
are not stored in this repo. This module reads a local cache of their public
zips and writes summary statistics only.
"""

from __future__ import annotations

import json
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_STORE_PATH = Path("docs/data/value_factor_base_rate.json")
MISSING_TITLE = "Value factor base rate missing"
STALE_TITLE = "Value factor base rate is stale"
STALE_AFTER_MONTHS = 18

_DATA_CUT_RE = re.compile(r"\b(19|20)\d{4}\b")
_YYYYMM_RE = re.compile(r"^(\d{6})$")

# Top-level zip names on mba.tuck.dartmouth.edu/.../ftp/
US_FACTORS = "F-F_Research_Data_Factors_CSV.zip"
EUROPE_FACTORS = "Europe_3_Factors_CSV.zip"
DEV_EX_US_FACTORS = "Developed_ex_US_3_Factors_CSV.zip"
US_BE_ME = "Portfolios_Formed_on_BE-ME_CSV.zip"
US_BE_ME_EX_DIV = "Portfolios_Formed_on_BE-ME_Wout_Div_CSV.zip"
US_EP = "Portfolios_Formed_on_E-P_CSV.zip"
US_EP_EX_DIV = "Portfolios_Formed_on_E-P_Wout_Div_CSV.zip"
US_CFP = "Portfolios_Formed_on_CF-P_CSV.zip"
US_CFP_EX_DIV = "Portfolios_Formed_on_CF-P_Wout_Div_CSV.zip"
US_DP = "Portfolios_Formed_on_D-P_CSV.zip"
US_DP_EX_DIV = "Portfolios_Formed_on_D-P_Wout_Div_CSV.zip"
EUROPE_6 = "Europe_6_Portfolios_ME_BE-ME_CSV.zip"
COUNTRIES = "F-F_International_Countries.zip"

SOURCE_PAGE = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html"


def read_zip_member(path: Path, member: str | None = None) -> str:
    """Read one text member from a French zip (CSV, or a named country file)."""
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if not name.endswith("/")]
        if member is None:
            chosen = next((name for name in names if name.lower().endswith(".csv")), names[0])
        else:
            chosen = next(name for name in names if name == member or name.endswith("/" + member))
        return archive.read(chosen).decode("latin1")


def data_cut(text: str) -> str | None:
    """Return the YYYYMM database stamp from the file preamble, if present."""
    head = "\n".join(text.splitlines()[:8])
    match = _DATA_CUT_RE.search(head)
    return match.group(0) if match else None


def _parse_number(token: str) -> float | None:
    try:
        value = float(token)
    except ValueError:
        return None
    if value <= -99.99:
        return None
    return value


def parse_french_monthly_csv(text: str) -> list[dict[str, Any]]:
    """Parse return blocks whose rows are YYYYMM.

    Annual blocks and firm-count blocks are ignored. Each block keeps the
    title line above its header.
    """
    lines = text.splitlines()
    blocks: list[dict[str, Any]] = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        markers = ("Lo 30", "Mkt-RF", "HiBM", "LoBM")
        if not line.startswith(",") or not any(marker in line for marker in markers):
            index += 1
            continue
        columns = [part.strip() for part in line.split(",")[1:]]
        title = ""
        for back in range(index - 1, max(-1, index - 6), -1):
            previous = lines[back].strip()
            if previous:
                title = previous
                break
        rows: dict[int, dict[str, float]] = {}
        index += 1
        while index < len(lines):
            raw = lines[index].strip()
            if not raw:
                break
            parts = [part.strip() for part in raw.split(",")]
            stamp = _YYYYMM_RE.match(parts[0])
            if stamp is None:
                break
            yyyymm = int(stamp.group(1))
            values: dict[str, float] = {}
            for name, token in zip(columns, parts[1:], strict=False):
                if not name:
                    continue
                parsed = _parse_number(token)
                if parsed is not None:
                    values[name] = parsed
            if values:
                rows[yyyymm] = values
            index += 1
        if rows and ("Return" in title or "Mkt-RF" in columns):
            blocks.append({"title": title, "columns": columns, "rows": rows})
        continue
    return blocks


def parse_uk_local_monthly(text: str) -> dict[int, dict[str, float]]:
    """UK value-weight local-currency monthly returns, four ratios not required.

    Columns follow the French country file: market, then high/low book-to-market,
    earnings/price, cash-earnings/price, and dividend yield, then zero-yield.
    """
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if "Value-Weight Local" in line and "Not Reqd" in line:
            start = index
            break
    if start is None:
        raise ValueError("UK local-currency monthly block not found")
    rows: dict[int, dict[str, float]] = {}
    keys = (
        "mkt",
        "bm_high",
        "bm_low",
        "ep_high",
        "ep_low",
        "cep_high",
        "cep_low",
        "dp_high",
        "dp_low",
        "dp_zero",
    )
    for line in lines[start + 1 :]:
        parts = line.split()
        if not parts:
            if rows:
                break
            continue
        stamp = _YYYYMM_RE.match(parts[0])
        if stamp is None:
            if rows:
                break
            continue
        if len(parts) < 11:
            continue
        parsed = [_parse_number(token) for token in parts[1:11]]
        if parsed[0] is None:
            continue
        rows[int(stamp.group(1))] = {
            key: value for key, value in zip(keys, parsed, strict=True) if value is not None
        }
    if not rows:
        raise ValueError("UK local-currency monthly rows were empty")
    return rows


def summarise_percent(values: list[float]) -> dict[str, Any]:
    """Summarise a monthly percent series. Arithmetic premium is 12 × mean."""
    count = len(values)
    if count < 2:
        return {"months": count}
    mean = sum(values) / count
    variance = sum((value - mean) ** 2 for value in values) / (count - 1)
    std = variance**0.5
    t_stat = mean / (std / count**0.5) if std else None
    growth = 1.0
    for value in values:
        growth *= 1.0 + value / 100.0
    geometric = growth ** (12.0 / count) - 1.0
    return {
        "months": count,
        "annualised_arithmetic_pct": round(mean * 12.0, 2),
        "annualised_geometric_pct": round(geometric * 100.0, 2),
        "annualised_volatility_pct": round(std * (12.0**0.5), 2),
        "t_stat": None if t_stat is None else round(t_stat, 2),
    }


def _slice_map(
    series: dict[int, float],
    *,
    start: int | None = None,
    end: int | None = None,
) -> list[float]:
    return [
        series[key]
        for key in sorted(series)
        if (start is None or key >= start) and (end is None or key <= end)
    ]


def _last_months(series: dict[int, float], months: int) -> list[float]:
    keys = sorted(series)
    return [series[key] for key in keys[-months:]]


def window_stats(series: dict[int, float]) -> dict[str, Any]:
    """Full sample, from 1990-07, the 2007-2020 stretch, and the last 10 years."""
    if not series:
        return {}
    keys = sorted(series)
    windows = {
        "full": _slice_map(series),
        "from_199007": _slice_map(series, start=199007),
        "from_200701_to_202012": _slice_map(series, start=200701, end=202012),
        "last_120_months": _last_months(series, 120),
    }
    return {
        "start": keys[0],
        "end": keys[-1],
        "windows": {
            name: summarise_percent(values) for name, values in windows.items() if len(values) >= 24
        },
    }


def _column(block: dict[str, Any], name: str) -> dict[int, float]:
    return {yyyymm: row[name] for yyyymm, row in block["rows"].items() if name in row}


def _subtract(left: dict[int, float], right: dict[int, float]) -> dict[int, float]:
    return {key: left[key] - right[key] for key in left.keys() & right.keys()}


def _average(maps: list[dict[int, float]]) -> dict[int, float]:
    keys = set.intersection(*(set(item) for item in maps)) if maps else set()
    return {key: sum(item[key] for item in maps) / len(maps) for key in keys}


def _block(blocks: list[dict[str, Any]], *, contains: str) -> dict[str, Any]:
    for block in blocks:
        if contains.lower() in block["title"].lower():
            return block
    raise KeyError(contains)


def _market_total(factors_text: str) -> dict[int, float]:
    blocks = parse_french_monthly_csv(factors_text)
    factor_block = next(block for block in blocks if "Mkt-RF" in block["columns"])
    excess = _column(factor_block, "Mkt-RF")
    risk_free = _column(factor_block, "RF")
    market = _subtract(excess, {key: -value for key, value in risk_free.items()})
    hml = _column(factor_block, "HML")
    return {"market": market, "hml": hml, "mkt_rf": excess}


def _high_low_market(
    block: dict[str, Any],
    market: dict[int, float],
    *,
    high: str,
    low: str,
) -> dict[str, Any]:
    high_leg = _column(block, high)
    low_leg = _column(block, low)
    return {
        "high_minus_low": window_stats(_subtract(high_leg, low_leg)),
        "high_minus_market": window_stats(_subtract(high_leg, market)),
        "low_minus_market": window_stats(_subtract(low_leg, market)),
    }


def build_value_factor_base_rate(cache_dir: Path) -> dict[str, Any]:
    """Summarise a local cache of French zips. Does not download or store raw rows."""
    cache_dir = Path(cache_dir)
    us_factors = read_zip_member(cache_dir / US_FACTORS)
    us_market = _market_total(us_factors)
    europe_factors = read_zip_member(cache_dir / EUROPE_FACTORS)
    europe_market = _market_total(europe_factors)
    dev_factors = read_zip_member(cache_dir / DEV_EX_US_FACTORS)
    dev_market = _market_total(dev_factors)

    def us_sort(zip_name: str) -> dict[str, Any]:
        text = read_zip_member(cache_dir / zip_name)
        blocks = parse_french_monthly_csv(text)
        value_weight = _block(blocks, contains="Value Weight Returns -- Monthly")
        equal_weight = _block(blocks, contains="Equal Weight Returns -- Monthly")
        return {
            "data_cut": data_cut(text),
            "value_weight": _high_low_market(
                value_weight, us_market["market"], high="Hi 30", low="Lo 30"
            ),
            "equal_weight": _high_low_market(
                equal_weight, us_market["market"], high="Hi 30", low="Lo 30"
            ),
        }

    us_sorts = {
        "book_to_market": us_sort(US_BE_ME),
        "earnings_price": us_sort(US_EP),
        "cashflow_price": us_sort(US_CFP),
        "dividend_yield": us_sort(US_DP),
    }
    us_sorts_ex_div = {
        "book_to_market": us_sort(US_BE_ME_EX_DIV),
        "earnings_price": us_sort(US_EP_EX_DIV),
        "cashflow_price": us_sort(US_CFP_EX_DIV),
        "dividend_yield": us_sort(US_DP_EX_DIV),
    }

    # Equal-weight of the four high-30 value-weight legs, minus the market.
    # Closest published analogue of composite_value's cheapness blend.
    def four_leg(weight_title: str) -> dict[int, float]:
        legs = []
        for zip_name in (US_BE_ME, US_EP, US_CFP, US_DP):
            blocks = parse_french_monthly_csv(read_zip_member(cache_dir / zip_name))
            legs.append(_column(_block(blocks, contains=weight_title), "Hi 30"))
        return _subtract(_average(legs), us_market["market"])

    blend_spread = four_leg("Value Weight Returns -- Monthly")
    equal_blend_spread = four_leg("Equal Weight Returns -- Monthly")

    europe_blocks = parse_french_monthly_csv(read_zip_member(cache_dir / EUROPE_6))
    europe_vw = _block(europe_blocks, contains="Value Weighted Returns -- Monthly")
    big_high = _column(europe_vw, "BIG HiBM")
    big_low = _column(europe_vw, "BIG LoBM")
    small_high = _column(europe_vw, "SMALL HiBM")
    small_low = _column(europe_vw, "SMALL LoBM")
    europe_hml_rebuilt = _subtract(
        _average([small_high, big_high]),
        _average([small_low, big_low]),
    )

    uk_text = read_zip_member(cache_dir / COUNTRIES, member="UK.Dat")
    uk = parse_uk_local_monthly(uk_text)
    uk_market = {key: row["mkt"] for key, row in uk.items() if "mkt" in row}

    def uk_pair(high_key: str, low_key: str) -> dict[str, Any]:
        high = {key: row[high_key] for key, row in uk.items() if high_key in row}
        low = {key: row[low_key] for key, row in uk.items() if low_key in row}
        return {
            "high_minus_low": window_stats(_subtract(high, low)),
            "high_minus_market": window_stats(_subtract(high, uk_market)),
        }

    return {
        "schema": "value_factor_base_rate.v1",
        "built_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "source": {
            "page": SOURCE_PAGE,
            "copyright": "Eugene F. Fama and Kenneth R. French",
            "us_data_cut": data_cut(us_factors),
            "europe_data_cut": data_cut(europe_factors),
            "developed_ex_us_data_cut": data_cut(dev_factors),
            "raw_files_stored": False,
        },
        "not_this_screen": (
            "These are published Fama/French portfolios. They are not "
            "assign_signal, composite_value, or the FTSE paper books."
        ),
        "us_hml": window_stats(us_market["hml"]),
        "europe_hml": window_stats(europe_market["hml"]),
        "developed_ex_us_hml": window_stats(dev_market["hml"]),
        "us_sorts_total_return": us_sorts,
        "us_sorts_ex_dividend": us_sorts_ex_div,
        "us_four_leg_value_blend_minus_market": {
            "value_weight": window_stats(blend_spread),
            "equal_weight": window_stats(equal_blend_spread),
            "note": (
                "Each month, the average of the Hi-30 book-to-market, earnings/price, "
                "cashflow/price and dividend-yield portfolios, minus the CRSP market. "
                "Value-weight is the large-cap mix. Equal-weight is closer to a broad buy tier."
            ),
        },
        "europe_big_value": {
            "high_minus_low": window_stats(_subtract(big_high, big_low)),
            "high_minus_market": window_stats(_subtract(big_high, europe_market["market"])),
            "rebuilt_hml": window_stats(europe_hml_rebuilt),
        },
        "uk_local_value_weight": {
            "currency": "local",
            "universe_note": (
                "MSCI country portfolios 1975-2006, Bloomberg thereafter. "
                "Value-weighted. Weaker on delisted names than the US CRSP sorts."
            ),
            "book_to_market": uk_pair("bm_high", "bm_low"),
            "earnings_price": uk_pair("ep_high", "ep_low"),
            "cash_earnings_price": uk_pair("cep_high", "cep_low"),
            "dividend_yield": uk_pair("dp_high", "dp_low"),
        },
    }


def write_value_factor_base_rate(payload: dict[str, Any], path: Path = DEFAULT_STORE_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _cut_to_month(cut: str) -> tuple[int, int]:
    return int(cut[:4]), int(cut[4:6])


def base_rate_is_stale(payload: dict[str, Any], *, today: datetime | None = None) -> bool:
    cut = str((payload.get("source") or {}).get("us_data_cut") or "")
    if not _YYYYMM_RE.match(cut):
        return True
    year, month = _cut_to_month(cut)
    current = today or datetime.now(UTC)
    age = (current.year - year) * 12 + (current.month - month)
    return age > STALE_AFTER_MONTHS


def finding_for_store(path: Path, *, today: datetime | None = None) -> dict[str, str] | None:
    """Read a summary file and return a freshness finding, or None."""
    if not path.exists():
        return ops_finding_from_base_rate(None)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return ops_finding_from_base_rate(None)
    if not isinstance(payload, dict):
        return ops_finding_from_base_rate(None)
    return ops_finding_from_base_rate(payload, today=today)


def ops_finding_from_base_rate(
    payload: dict[str, Any] | None,
    *,
    today: datetime | None = None,
) -> dict[str, str] | None:
    """Warn only when the committed summary is missing or older than 18 months."""
    if not payload:
        return {
            "severity": "warn",
            "category": "backtest",
            "title": MISSING_TITLE,
            "summary": (
                "docs/data/value_factor_base_rate.json is missing. "
                "Refresh from a local Ken French cache; do not treat paper excess as the value base rate."
            ),
        }
    if base_rate_is_stale(payload, today=today):
        cut = (payload.get("source") or {}).get("us_data_cut")
        return {
            "severity": "warn",
            "category": "backtest",
            "title": STALE_TITLE,
            "summary": (
                f"US French data cut {cut} is more than {STALE_AFTER_MONTHS} months old. "
                "Recompute the summary before citing it against the live books."
            ),
        }
    return None
