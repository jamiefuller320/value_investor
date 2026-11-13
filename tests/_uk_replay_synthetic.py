"""Deterministic synthetic EODHD-shaped records for UK replay equivalence tests.

No licensed data: every price and statement is generated from a seeded RNG.
"""

from __future__ import annotations

import hashlib
import json
import random
from datetime import date, timedelta
from typing import Any

SECTORS = ["Industrials", "Consumer Cyclical", "Financial Services", "Technology"]


def _business_days(start: date, end: date) -> list[date]:
    days = []
    day = start
    while day <= end:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


def _statements(rng: random.Random, first_year: int, last_year: int, base: float) -> dict:
    income: dict[str, Any] = {}
    cash: dict[str, Any] = {}
    sheet: dict[str, Any] = {}
    earnings: dict[str, Any] = {}
    quarterly: dict[str, Any] = {}
    history: dict[str, Any] = {}
    revenue = base
    for year in range(first_year, last_year + 1):
        revenue *= 1.0 + rng.uniform(-0.25, 0.15)
        end = date(year, 12, 31)
        filing = end + timedelta(days=rng.randint(40, 200))
        operating = revenue * rng.uniform(-0.05, 0.2)
        net = operating * rng.uniform(0.5, 0.9)
        ocf = operating * rng.uniform(0.6, 1.3)
        capex = -abs(revenue * rng.uniform(0.01, 0.08))
        income[end.isoformat()] = {
            "date": end.isoformat(),
            "filing_date": filing.isoformat() if rng.random() > 0.1 else None,
            "totalRevenue": f"{revenue:.2f}",
            "operatingIncome": f"{operating:.2f}",
            "ebit": f"{operating:.2f}",
            "ebitda": f"{operating * 1.2:.2f}",
            "netIncome": f"{net:.2f}",
            "grossProfit": f"{revenue * 0.4:.2f}",
            "interestExpense": f"{revenue * 0.01:.2f}",
        }
        cash[end.isoformat()] = {
            "date": end.isoformat(),
            "totalCashFromOperatingActivities": f"{ocf:.2f}",
            "capitalExpenditures": f"{capex:.2f}",
        }
        sheet[end.isoformat()] = {
            "date": end.isoformat(),
            "totalAssets": f"{revenue * 1.5:.2f}",
            "totalCurrentAssets": f"{revenue * 0.6:.2f}",
            "totalLiab": f"{revenue * 0.9:.2f}",
            "totalCurrentLiabilities": f"{revenue * 0.4:.2f}",
            "shortTermDebt": f"{revenue * 0.1:.2f}",
            "longTermDebt": f"{revenue * 0.3:.2f}",
            "cashAndShortTermInvestments": f"{revenue * 0.2:.2f}",
            "totalStockholderEquity": f"{revenue * 0.6:.2f}",
            "commonStockSharesOutstanding": f"{1e8:.0f}",
        }
        if rng.random() > 0.3:
            earnings[end.isoformat()] = {"date": end.isoformat(), "epsActual": net / 1e8}
        for quarter, month in enumerate((3, 6, 9, 12)):
            q_end = date(year, month, 28)
            quarterly[q_end.isoformat()] = {
                "date": q_end.isoformat(),
                "filing_date": (q_end + timedelta(days=45)).isoformat(),
                "totalRevenue": f"{revenue / 4 * (1 + 0.05 * quarter):.2f}",
            }
            history[q_end.isoformat()] = {
                "date": q_end.isoformat(),
                "reportDate": (q_end + timedelta(days=30)).isoformat(),
                "epsActual": net / 4e8 * rng.uniform(0.7, 1.2),
            }
    return {
        "Financials": {
            "Income_Statement": {"yearly": income, "quarterly": quarterly},
            "Cash_Flow": {"yearly": cash},
            "Balance_Sheet": {"yearly": sheet},
        },
        "Earnings": {"Annual": earnings, "History": history},
    }


def synthetic_records(
    *,
    seed: int = 20261113,
    lse_names: int = 18,
    xetra_names: int = 8,
    start: date = date(2012, 1, 2),
    end: date = date(2016, 6, 30),
    shares_as_list: bool = False,
) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    calendar = _business_days(start, end)
    records: list[dict[str, Any]] = []
    plan = [("LSE", "ftse350", "GBX", lse_names), ("XETRA", "dax", "EUR", xetra_names)]
    for exchange, market, currency, count in plan:
        for index in range(count):
            code = f"{exchange[0]}{index:02d}"
            symbol = f"{code}.{exchange}"
            delisted = rng.random() < 0.25
            first = rng.randint(0, 150)
            last = len(calendar) - 1
            if delisted:
                last = rng.randint(len(calendar) // 2, len(calendar) - 20)
            price = rng.uniform(50, 400)
            bars = []
            no_high_low = rng.random() < 0.2
            drift = rng.uniform(-0.0008, 0.0008)
            for day in calendar[first : last + 1]:
                price = max(1.0, price * (1.0 + drift + rng.gauss(0, 0.018)))
                if rng.random() < 0.01:
                    continue
                adjusted = price * 0.97
                row = {
                    "date": day.isoformat(),
                    "open": round(price, 4),
                    "close": round(price, 4),
                    "adjusted_close": round(adjusted, 4),
                    "volume": rng.randint(1000, 100000),
                }
                if not no_high_low:
                    row["high"] = round(price * 1.01, 4)
                    row["low"] = round(price * 0.99, 4)
                bars.append(row)
            if rng.random() < 0.05 and bars:
                bars.append(dict(bars[-1]))
            sector = rng.choice(SECTORS + [None]) if index > 2 else SECTORS[index % 2]
            general = {
                "Name": f"Synthetic {code} plc",
                "Type": "Common Stock",
                "CurrencyCode": currency,
                "ISIN": f"GB00{index:08d}" if exchange == "LSE" else f"DE00{index:08d}",
                "Industry": "Machinery",
            }
            if sector:
                general["Sector"] = sector
            fundamentals = _statements(rng, 2008, 2016, rng.uniform(50e6, 5e9))
            fundamentals["General"] = general
            shares = rng.uniform(5e7, 2e9)
            fundamentals["outstandingShares"] = {
                "annual": {
                    str(i): {"dateFormatted": f"{year}-12-31", "shares": shares * (1 + 0.01 * i)}
                    for i, year in enumerate(range(2009, 2017))
                },
                "quarterly": {
                    "0": {"dateFormatted": "2014-06-30", "shares": shares * 1.02},
                },
            }
            if shares_as_list:
                block = fundamentals["outstandingShares"]
                block["annual"] = list(block["annual"].values())
                block["quarterly"] = list(block["quarterly"].values())
            splits = []
            if rng.random() < 0.15:
                splits.append({"date": "2014-03-14", "split": "2.000000/1.000000"})
            dividends = [
                {"date": f"{year}-0{month}-15", "value": round(rng.uniform(1, 10), 3)}
                for year in range(2011, 2017)
                for month in (4, 9)
            ]
            record: dict[str, Any] = {
                "symbol": symbol,
                "market": market,
                "name": general["Name"],
                "currency": currency,
                "delisted": delisted,
                "isin": general["ISIN"],
                "eod": bars,
                "fundamentals": fundamentals,
                "dividends": dividends,
                "splits": splits,
            }
            if exchange == "LSE" and index in (3, 7):
                record["ch_key"] = "gkn" if index == 7 else f"synthetic_{index}"
                record["ch_filings"] = [
                    {
                        "fiscal_year": year,
                        "fiscal_year_end": f"{year}-12-31",
                        "filing_date": f"{year + 1}-04-20",
                        "fields": {
                            "revenue": {"value": str(900 + 10 * year), "scale": "millions"},
                            "operating_profit": {"value": "50", "scale": "millions"},
                            "basic_eps": {"value": "12.5", "scale": None},
                        },
                    }
                    for year in (2011, 2012)
                ]
            records.append(record)
    return records


def _canon(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _canon(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [_canon(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_canon(v) for v in value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        return repr(value)
    if hasattr(value, "tolist"):
        return _canon(value.tolist())
    if hasattr(value, "__dataclass_fields__"):
        return _canon({k: getattr(value, k) for k in value.__dataclass_fields__})
    return value


def spec_digest_rows(specs: list[Any]) -> list[Any]:
    rows = []
    for spec in specs:
        gates = spec.gates
        tape_rows = []
        if hasattr(gates, "as_of"):
            for index in range(len(gates)):
                fact = gates.fact(index)
                tape_rows.append(_canon(fact))
        rows.append(
            {
                "ticker": spec.ticker,
                "market": spec.market,
                "sessions": _canon(list(spec.sessions or [])),
                "closes": _canon([float(v) for v in spec.closes or []]),
                "highs": None if spec.highs is None else _canon([float(v) for v in spec.highs]),
                "lows": None if spec.lows is None else _canon([float(v) for v in spec.lows]),
                "universe": _canon(spec.universe),
                "book_key": spec.book_key,
                "screens": _canon(spec.screens),
                "gates": tape_rows,
            }
        )
    return rows


def digest(payload: Any) -> str:
    text = json.dumps(_canon(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _scrub_times(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _scrub_times(v) for k, v in value.items() if not str(k).endswith("_at")}
    if isinstance(value, list):
        return [_scrub_times(v) for v in value]
    return value


def run_pipeline(records: list[dict[str, Any]], repo_root: Any) -> dict[str, str]:
    """Digest every development output on synthetic records."""
    import copy

    from value_investor import strategy_book_uk_replay as uk

    constants = uk.REGISTRATION_CONSTANTS
    saved = constants["EXCHANGES"]
    constants["EXCHANGES"] = {
        "LSE": {"market": "ftse350", "rank_count": 6, "rank_currency": "GBP"},
        "XETRA": {"market": "dax", "rank_count": 3, "rank_currency": "EUR"},
        "PA": {"market": "cac40", "rank_count": 3, "rank_currency": "EUR"},
    }
    try:
        eurgbp = {day: 0.85 for day in _business_days(date(2011, 1, 3), date(2017, 1, 31))}
        usdgbp = {day: 0.7 for day in eurgbp}
        assembled = uk.assemble_specs(
            copy.deepcopy(records), eurgbp=eurgbp, usdgbp=usdgbp, ch_store={"names": []}
        )
        before = spec_digest_rows(assembled["specs"])
        uk.apply_sector_frame(assembled["specs"], uk._prepared_view(copy.deepcopy(records)))
        after = spec_digest_rows(assembled["specs"])
        results = uk.walk_variants(
            assembled["specs"],
            assembled["haircuts"],
            last_signal=str(constants["DEVELOPMENT_END"]),
        )
        store = uk.develop(
            repo_root=repo_root,
            records=copy.deepcopy(records),
            eurgbp=eurgbp,
            usdgbp=usdgbp,
            ch_store={"names": []},
        )
    finally:
        constants["EXCHANGES"] = saved
    meta = {k: v for k, v in assembled.items() if k not in {"specs", "prepared"}}
    store = _scrub_times(store)
    return {
        "assembled_meta": digest(meta),
        "specs_before_sector": digest(before),
        "specs_after_sector": digest(after),
        "results": digest(results),
        "store": digest(store),
    }
