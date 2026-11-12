# EODHD coverage check — step 3.3 data trial

Observe-only instrument for [strategy step 3.3](strategy-reorientation-plan.md). It
does **not** build a replay. It answers one question before any UK/Europe point-in-time
work: is [EOD Historical Data](https://eodhd.com/) (EODHD) good enough for a
survivorship-free, point-in-time replay of the strategy book's filters?

LSEG, FactSet and similar institutional feeds were ruled out on cost (owner,
2026-11-11). This trial uses the ALL-IN-ONE plan (~$99.99 for one month).

## What pass, partial and fail mean

| Verdict | Meaning for step 3.3 |
|---------|----------------------|
| **pass** | Checks A (survivorship names), B (active sample quality) and D (market-cap feasibility) all meet the pre-set bars. The owner may proceed to design a non-US replay on EODHD. |
| **partial** | Survivorship check A passed, but active-sample depth or market-cap feasibility fell short. Worth a conversation (narrower universe, manual fixes, or a different source) before committing replay engineering. |
| **fail** | Survivorship check A failed — delisted UK/Europe names or price/fundamental history are too thin. Do not build the replay on EODHD; cancel the subscription unless you want to re-run after a product change. |

Overall rule: **pass** when A, B and D pass; **partial** when A passes but B or D does not; **fail** when A fails.

## Owner steps

1. Subscribe to EODHD **ALL-IN-ONE** for one month.
2. In GitHub → Settings → Secrets → Actions, add `EODHD_API_TOKEN` (the API token from the EODHD dashboard). Never commit it.
3. Run **EODHD coverage check** (`eodhd-coverage-check.yml`) via **workflow_dispatch**.
4. Read `docs/data/eodhd_coverage_check.json` (or the ops-monitor info finding **EODHD coverage check**).
5. If the verdict is **fail** or you do not need the feed, cancel the subscription and remove the secret.

CLI for a local trial (same licence rules — do not commit raw API output):

```bash
export EODHD_API_TOKEN='…'   # not in shell history you sync
ftse-eodhd-coverage --out docs/data/eodhd_coverage_check.json
```

## Licence and what is committed

EODHD data is **not** redistributable. The committed report holds aggregates only:
verdict, pass-bar constants, booleans, dates, ticker codes and counts. **No** prices,
financial values or raw API bodies. Raw responses exist only in memory (or a temp
directory deleted when the run ends).

## Pass bars (fixed before data)

See module constants in `src/value_investor/eodhd_coverage_check.py` and the
`pass_bars` block in the report.

- **Check A — Survivorship (11 names):** at least **8** found (delisted list first, then search, whole-word
  name match) with daily prices running to no earlier than 10 trading days before the event
  date (later prices are fine; the event dates are approximate failure/takeover dates), and fundamentals depth from **2013** on at least **7**.
- **Check B — Active sample (30 FTSE 350 + 10 euro):** fundamentals depth from 2013 on
  ≥**80%**; annual periods with filing/report dates ≥**70%** (share across 2013–2025);
  currency code on ≥**95%**; shares-outstanding history on ≥**80%**; EOD from 2013 on ≥
  **80%**.
- **Check C — Universe breadth:** LSE active and delisted common-stock counts (report only).
- **Check D — Membership feasibility:** on four snapshot dates, close × latest
  shares-outstanding on or before the date computable for ≥**80%** of the active sample
  (FTSE 350 membership history is not available — this proxies feasibility).

## Limits (not a full PIT proof)

- Filing and report **dates** are checked; full restatement detection is not.
- FTSE 350 membership is **not** historical — replay would approximate by market-cap rank.
- Any future replay must **not** use LLM memo verdicts on the capital path (same as the US
  rehearsal).
- Euro symbols use exchange codes **LSE**, **XETRA** and **PA** (Paris) per EODHD.

## First run (2026-11-12)

Verdict **fail**, 564 calls. Read per check:

- **A, prices:** 10 of 11 failed names found in the delisted list with prices to the event.
  Patisserie's prices stop at its October 2018 suspension, before the administration date
  used as its event date.
- **A, fundamentals:** only 3 of 11 have statements from 2013 (Aggreko, Morrison,
  Wirecard; intu from 2016). Carillion, Thomas Cook, Debenhams, Patisserie, Sirius, GKN and
  Sky return company details but no statements. This is the real gap: the failures a
  survivorship-free replay most needs are the names without fundamentals.
- **B, active sample:** pass (statements from 2013 on 85%, dated periods 99.8%, currency
  100%, shares history 97.5%). Misses are names listed after 2013.
- **D:** the 0% was a parsing bug, not missing data. EODHD puts a bare year or quarter in
  `outstandingShares[*].date`; the check now reads `dateFormatted`. Re-run to get the true D
  share. The bars were not changed after seeing the results.

## Automation

- **Workflow:** `.github/workflows/eodhd-coverage-check.yml` (dispatch only). Missing
  secret → exit 0, no commit.
- **Ops-monitor:** `check_eodhd_coverage` — info with verdict when the report exists; no
  finding when absent; warn if unreadable. `auto_fixable=false`. `influences_live=false`.

Sample sources:

- FTSE 350: committed `docs/data/library/t212_coverage/by_market/ftse350.json`, 30 names
  evenly spaced through the ticker-sorted list (no live fetch, not one letter of the alphabet).
- Euro: `docs/data/library/markets/dax/constituents/latest.json` and `…/cac40/…` (five
  names each, evenly spaced by ticker).
