# Phase 1 gate review pack (owner, 2026-11-11)

**Outcome: ACCEPTED with one adjustment, owner, 2026-11-10.** Both gates accepted as they are, including the "at least 50%" sector line. The one adjustment: funds and investment trusts get `insufficient_data` from the decline gate, logged as a change marker. See [owner decision](#owner-decision-2026-11-10). `forward_live` is not set by this decision.

**Decision asked of the owner:** the Phase 1 gate in
[`strategy-reorientation-plan.md`](strategy-reorientation-plan.md#phase-1--filters-and-foundations-observe-only):
"review the gate verdicts on a sample of 10 FTSE buy-tier names (5 flagged, 5 clear) against the
cited evidence. Accept, adjust thresholds once (logged), or reject." Owner, 2026-11-05: this review
governs only when the forward book (step 2.3) of `owner-strategy-book-v0` goes live. It does not
touch the archive replay, the US rehearsal or the signature.

**Strategy parts served:** part 2 (not declining) and part 3 (sector sound).

**Human task:** `adhoc-strategy-phase-gate` in
[`human-tasks-checklist.md`](human-tasks-checklist.md#ad-hoc-when-triggered). Go-live itself is
`adhoc-strategy-book-memo-spend`.

**Prepared 2026-11-10** from main at `0cc711d55a`. Gate stores read: `docs/data/operating_decline_gate.json`
and `docs/data/sector_headwind_gate.json`, both `as_of` 2026-11-10, refreshed by ops-monitor at
02:33 UTC and committed in `5fe99562bf`. FTSE screen date 2026-11-08. The numbers below are copied
from those stores. Later refreshes will move them; to see exactly what this pack saw, run
`git show 5fe99562bf:docs/data/operating_decline_gate.json`.

**Read first.** [Go-live readiness](#go-live-readiness) lists a code defect that stops the forward
book from opening any entry, whether `forward_live` is true or not. Accepting the gates on 2026-11-11
is still possible. Setting `forward_live` should wait for that fix.

## 1. The two gates in one paragraph each

**Operating-decline gate (part 2)**, `src/value_investor/operating_decline_gate.py`,
[runbook](operating-decline-gate.md#checks-and-thresholds-v0). Per name: `clear`, `declining` or
`insufficient_data`. Any one **hard** check makes the name `declining`, and so do two **soft**
checks. The name is `insufficient_data` when nothing fired and revenue, plus margin or EPS, could not
be evaluated. Entry needs `clear`.

| Check | Kind | Fires when | Constant |
|---|---|---|---|
| Annual revenue | hard | latest fiscal year down more than 5% | `REVENUE_DROP_PCT = 0.05` |
| Two-year revenue | hard | both of the last two years down more than 1% | `REVENUE_FLAT_TOLERANCE_PCT = 0.01` |
| Interim revenue (year on year) | hard | down more than 5% | `INTERIM_REVENUE_DROP_PCT` |
| Operating margin | hard | down more than 3 percentage points | `MARGIN_DROP_PP = 0.03` |
| FCF turned negative | hard | negative after a positive year | — |
| Profit warning / guidance cut headline | hard | in the filings index within 180 days | `WARNING_LOOKBACK_DAYS = 180` |
| Annual EPS | soft | down more than 20% | `EPS_ANNUAL_DROP_PCT = 0.20` |
| Interim EPS (year on year) | soft | down more than 10% | `EPS_INTERIM_DROP_PCT = 0.10` |
| FCF sharp fall | soft | down more than 50% | `FCF_SHARP_FALL_PCT = 0.50` |
| Dividend cut flag, impairment / downgrade headline | soft | flag or headline present | — |
| Soft signals needed | — | 2 | `SOFT_SIGNALS_TO_DECLINE = 2` |

**Sector headwind gate (part 3)**, `src/value_investor/sector_headwind_gate.py`,
[runbook](sector-headwind-gate.md#verdict-rule). Per sector, within the name's own market (or its
region when the market has fewer than 4 members in that sector). The verdict is `headwind` when
**either** trigger fires, `sound` when neither fires and all three inputs have enough coverage, and
`insufficient_data` otherwise. Entry needs `sound`.

| Trigger | Fires when | Constant |
|---|---|---|
| Price breadth **and** trend | at least 65% of members below their 200-day average **and** the equal-weight 126-day return below −10% | `PRICE_BREADTH_HEADWIND = 0.65`, `SECTOR_RETURN_126D_HEADWIND = -0.10` |
| Operating-decline breadth | at least 50% of covered members `declining` in the decline store | `DECLINE_BREADTH_HEADWIND = 0.50` (`EARNINGS_BREADTH_HEADWIND` for the screen-field fallback) |
| Coverage | each input needs 4+ members and 60% coverage | `MIN_MEMBERS_WITH_DATA = 4`, `MIN_COVERAGE_SHARE = 0.60` |

## 2. How the sample was chosen

The pool is every FTSE 350 name in the decline store with `signal` `buy` or `strong_buy` (70
names). **Flagged** means decline verdict `declining` or sector verdict `headwind` (12 names).
**Clear** means decline `clear` and sector `sound` (54 names). The four names with an
`insufficient_data` verdict on either gate are in neither pool. They are listed in
[section 5](#5-names-outside-the-sample) so they can be checked too.

Within each pool, names are grouped by screen sector. Sectors are taken in order of how many pool
names they hold, most first, with ties broken alphabetically. From each of the first five sectors,
the name with the lowest `sha256("<ticker>|phase1-gate-2026-11-11")` is picked. That gives one name
per sector and five sectors per pool. No name was swapped after the draw.

```python
import collections, hashlib, json
dec = json.load(open("docs/data/operating_decline_gate.json"))
sec = json.load(open("docs/data/sector_headwind_gate.json"))
bt = {t: v for t, v in dec["names"].items()
      if v.get("market") == "ftse350" and v.get("signal") in ("buy", "strong_buy")}
sv = {t: sec["names"].get(t, {}).get("sector_verdict") for t in bt}
flagged = [t for t in bt if bt[t]["verdict"] == "declining" or sv[t] == "headwind"]
clear = [t for t in bt if bt[t]["verdict"] == "clear" and sv[t] == "sound"]
h = lambda t: hashlib.sha256(f"{t}|phase1-gate-2026-11-11".encode()).hexdigest()
def pick(pool):
    by = collections.defaultdict(list)
    for t in pool:
        by[bt[t].get("sector") or ""].append(t)
    order = sorted(by, key=lambda s: (-len(by[s]), s))
    return [min(by[s], key=h) for s in order[:5]]
print(pick(flagged), pick(clear))
```

Result on `5fe99562bf`: flagged `COST.L, INCH.L, SHEL.L, GCP.L, BT-A.L`; clear
`DNLM.L, DATA.L, IGG.L, BREE.L, IMB.L`.

What the draw does not cover: Utilities (CNA.L, the only buy-tier name there, is flagged on four
counts) and HBR.L, the only name flagged on the sector gate alone. Both are in
[section 5](#5-names-outside-the-sample).

## 3. The ten names

Sources: annual statements are `docs/data/research/<TICKER>/sources/financials_annual.json`
(Yahoo statements; "fetched" is that file's `fetched_at`). Half-year figures are
`filing_interim_financials.json`, extracted from the half-year results body; the citation is the
matched text. Headlines are `filings/filings_index.json`. Sector inputs are from
`docs/data/charts/<TICKER>.json` (closes and 200-day average) and the decline store. All checks are
as of 2026-11-10.

### Summary

| # | Ticker | Name | Sector | Decline | Sector | Deciding reason | Owner: agree / disagree / note |
|---|---|---|---|---|---|---|---|
| F1 | COST.L | Costain Group | Industrials | **declining** | sound | FY2025 revenue −16.4% (hard), second year down || agree (owner, 2026-11-10) |
| F2 | INCH.L | Inchcape | Consumer Cyclical | **declining** | sound | Revenue down two years (−1.8%, −1.3%) (hard), plus annual EPS −30% (soft) || agree (owner, 2026-11-10) |
| F3 | SHEL.L | Shell | Energy | **declining** | **headwind** | FY2025 revenue −6.1% (hard); Energy has 4 of 8 members declining (= 50%) || agree (owner, 2026-11-10) |
| F4 | GCP.L | GCP Infrastructure Investments | Financial Services | **declining** | sound | Revenue down two years (−4.3%, −33.4%) (hard) || agree it is blocked, for the wrong reason: a fund. Now `insufficient_data` (`fund_or_trust`) |
| F5 | BT-A.L | BT Group | Communication Services | **declining** | sound | Revenue down two years (−3.5%, −2.1%) (hard) || agree (owner, 2026-11-10) |
| C1 | DNLM.L | Dunelm Group | Consumer Cyclical | clear | sound | No check fired (interim EPS −7.3%, under the 10% line) || agree (owner, 2026-11-10) |
| C2 | DATA.L | GlobalData | Industrials | clear | sound | No check fired || agree (owner, 2026-11-10); balance-sheet check queued (L701) |
| C3 | IGG.L | IG Group | Financial Services | clear | sound | No check fired || agree (owner, 2026-11-10) |
| C4 | BREE.L | Breedon Group | Basic Materials | clear | sound | One soft signal only (interim EPS −16.1%) || agree (owner, 2026-11-10) |
| C5 | IMB.L | Imperial Brands | Consumer Defensive | clear | sound | No check fired (annual EPS −16.6%, under the 20% line) || agree (owner, 2026-11-10) |

### F1. COST.L — Costain Group (Industrials, `buy`)

Decline **declining**. Hard checks: `revenue_decline` and `revenue_two_year_decline`.

| Check | Evidence | Threshold | Fired |
|---|---|---|---|
| Revenue (Total Revenue) | FY2025 1,045.7m vs FY2024 1,251.1m, **−16.4%**; prior year −6.1% | −5%; two years each below −1% | yes (hard, both) |
| Interim revenue | not evaluable (`interim_revenue_missing`) | — | — |
| Operating margin | 4.28% vs 2.49%, +1.8 pp | −3 pp | no |
| Annual EPS (diluted) | 0.137 vs 0.111 | −20% | no |
| Interim EPS (adjusted) | 5.7p vs 5.5p, +3.6%, H1 to 2026-06-30, published 2026-08-13. Citation: "Adjusted EPS 1 5.7p 5.5p 3.6%" | −10% | no |
| FCF | 48.5m vs 33.6m | −50% / turned negative | no |
| Dividend flag; headlines | evaluable, none; 66 filings scanned over 180 days | — | no |

Data dates: statements fetched 2026-11-10 01:16 UTC, latest fiscal year 2025. Sector Industrials
**sound** (see [sector inputs](#sector-inputs)).

### F2. INCH.L — Inchcape (Consumer Cyclical, `strong_buy`)

Decline **declining**. Hard check `revenue_two_year_decline`, plus soft `eps_decline_annual`.

| Check | Evidence | Threshold | Fired |
|---|---|---|---|
| Revenue | FY2025 9,100m vs FY2024 9,263m, **−1.8%**; prior year **−1.3%** | two years each below −1% | yes (hard) |
| Interim revenue | £4,722m vs £4,320m, **+9.3%**, H1 to 2026-06-30, published 2026-07-28. Citation: "Revenue £4,722m £4,320m +9%" | −5% | no |
| Operating margin | 6.19% vs 6.30%, −0.1 pp | −3 pp | no |
| Annual EPS (diluted) | 0.716 vs 1.019, **−29.7%** | −20% | yes (soft) |
| Interim EPS | not evaluable (`interim_eps_not_on_screen_row`) | — | — |
| FCF | 337m vs 507m, −33.5% | −50% | no |
| Dividend flag; headlines | none; 56 scanned | — | no |

Data dates: statements fetched 2026-11-09 07:45 UTC, latest fiscal year 2025. Sector Consumer
Cyclical **sound**.

**For the owner:** the two-year rule fires on two small annual declines while the latest half-year
shows revenue up 9%. The hard annual check wins over the newer interim figure. The annual EPS fall
alone is one soft signal and would not flag the name on its own.

### F3. SHEL.L — Shell (Energy, `buy`)

Decline **declining**, from the hard checks `revenue_decline` and `revenue_two_year_decline`.
Sector Energy **headwind**, from `OPERATING_DECLINE_BREADTH_HEADWIND`.

| Check | Evidence | Threshold | Fired |
|---|---|---|---|
| Revenue | FY2025 266,886m vs FY2024 284,312m, **−6.1%**; prior year −10.2% | −5%; two years | yes (hard, both) |
| Interim revenue (quarterly series) | Q to 2026-09-30 92,848m vs 68,153m, **+36.2%** (`financials_annual.json quarterly_income`) | −5% | no |
| Operating margin | 10.33% vs 10.55%, −0.2 pp | −3 pp | no |
| Annual EPS | 3.00 vs 2.53, up | −20% | no |
| Interim EPS | not evaluable (`interim_metric_missing_on_latest_period`) | — | — |
| FCF | 23,916m vs 35,086m, −31.8% | −50% | no |
| Headlines | 156 scanned, none | — | no |

Energy sector (8 members): 4 declining (DCC.L, ENOG.L, ENQ.L, SHEL.L); 4 clear (BP.L, HBR.L, HTG.L,
ITH.L). That is **50.0%**, exactly on the ≥ 50% line. Price breadth is 3 of 8 (37.5%) below the
200-day average, and the 126-day return is +1.5%, so the price trigger is far off. Data dates:
statements fetched 2026-11-04 10:57 UTC.

**For the owner:** the revenue fall follows oil and gas prices, while margin and EPS held. SHEL.L
counts towards its own sector's headwind. If SHEL.L were `clear`, Energy would be 3 of 8 (37.5%),
hence `sound`, and HBR.L (which is `clear` on the decline gate) would no longer be blocked.

### F4. GCP.L — GCP Infrastructure Investments (Financial Services, `buy`)

Decline **declining**. Hard check `revenue_two_year_decline`.

| Check | Evidence | Threshold | Fired |
|---|---|---|---|
| Revenue | FY2025 21.4m vs FY2024 22.3m, **−4.3%**; prior year **−33.4%** | two years each below −1% | yes (hard) |
| Interim revenue | not evaluable | — | — |
| Operating margin | not evaluable (`operating_income_missing_or_stale`) | — | — |
| Annual EPS | 0.0215 vs 0.0225, −4.4% | −20% | no |
| Interim EPS | not evaluable | — | — |
| FCF | 123.7m vs 113.3m | — | no |
| Headlines | 113 scanned, none | — | no |

Data dates: statements fetched 2026-11-10 01:43 UTC, latest fiscal year 2025. Sector Financial
Services **sound**.

**For the owner:** this is a listed infrastructure fund. Its "revenue" line is investment income as
Yahoo reports it, and no operating margin exists. The gate applies company rules to a fund.

### F5. BT-A.L — BT Group (Communication Services, `buy`)

Decline **declining**. Hard check `revenue_two_year_decline`.

| Check | Evidence | Threshold | Fired |
|---|---|---|---|
| Revenue | FY2026 19,654m vs FY2025 20,358m, **−3.5%**; prior year **−2.1%** | two years each below −1% | yes (hard) |
| Interim revenue | not evaluable | — | — |
| Operating margin | 17.97% vs 17.12%, +0.9 pp | −3 pp | no |
| Annual EPS | 0.108 vs 0.106 | −20% | no |
| Interim EPS | not evaluable | — | — |
| FCF | 1,861m vs 2,052m, −9.3% | −50% | no |
| Headlines | 2 scanned, none | — | no |

Data dates: statements fetched 2026-11-10 00:08 UTC, latest fiscal year 2026 (March year end).
Sector Communication Services **sound**. BT-A.L entered the buy tier on the 2026-11-08 screen.

### C1. DNLM.L — Dunelm Group (Consumer Cyclical, `buy`)

Decline **clear**; no check fired.

| Check | Evidence | Threshold | Fired |
|---|---|---|---|
| Revenue | FY2026 +3.1%; prior year +3.8% | −5% | no |
| Interim revenue | £926.3m vs £893.7m, +3.6%, H1 to 2025-12-27, published 2026-02-10 | −5% | no |
| Operating margin | 12.32% vs 12.54%, −0.2 pp | −3 pp | no |
| Annual EPS | 0.768 vs 0.768 | −20% | no |
| Interim EPS (diluted) | 41.7p vs 45.0p, **−7.3%**. Citation: "Diluted earnings per share 41.7p 45.0p (7.3%)" | −10% | no |
| FCF | 227.7m vs 211.4m | — | no |
| Headlines | 19 scanned, none | — | no |

Data dates: statements fetched 2026-11-03 10:14 UTC. The half-year cited is about ten months old;
the FY2026 annual figures are newer. Sector Consumer Cyclical **sound**.

### C2. DATA.L — GlobalData (Industrials, `buy`)

Decline **clear**; no check fired.

| Check | Evidence | Threshold | Fired |
|---|---|---|---|
| Revenue | FY2025 +12.8%; prior year +4.5% | −5% | no |
| Interim revenue | £162.9m vs £156.5m, +4.1%, H1 to 2026-06-30, published 2026-09-14 | −5% | no |
| Operating margin | 25.15% vs 22.45%, +2.7 pp | −3 pp | no |
| Annual EPS | 0.044 vs 0.037 | −20% | no |
| Interim EPS (adjusted basic) | 2.7p vs 2.5p, +8% | −10% | no |
| FCF | 40.0m vs 38.3m | — | no |
| Headlines | 128 scanned, none | — | no |

Data dates: statements fetched 2026-11-03 10:14 UTC. Sector Industrials **sound**. The same
half-year table shows net bank debt up from £16.8m to £133.0m; the gate has no balance-sheet check.

### C3. IGG.L — IG Group (Financial Services, `buy`)

Decline **clear**; no check fired.

| Check | Evidence | Threshold | Fired |
|---|---|---|---|
| Revenue | FY2025 +11.3%; prior year −10.3% | two years | no |
| Interim revenue | £642.8m vs £545.2m, +17.9%, H1 to 2026-06-30, published 2026-07-30 | −5% | no |
| Operating margin | 35.90% vs 28.43%, +7.5 pp | −3 pp | no |
| Annual EPS | 1.051 vs 0.784 | −20% | no |
| Interim EPS (adjusted) | 68.9p vs 56.9p, +21.1% | −10% | no |
| FCF | 486.0m vs 379.5m | — | no |
| Headlines | 48 scanned, none | — | no |

Data dates: statements fetched 2026-11-10 01:26 UTC. Sector Financial Services **sound**.

### C4. BREE.L — Breedon Group (Basic Materials, `buy`)

Decline **clear**. One soft signal fired, `eps_decline_interim`; two are needed.

| Check | Evidence | Threshold | Fired |
|---|---|---|---|
| Revenue | FY2025 +8.7%; prior year +6.0% | −5% | no |
| Interim revenue | not evaluable (`interim_revenue_missing`) | — | — |
| Operating margin | 7.66% vs 9.89%, **−2.2 pp** | −3 pp | no |
| Annual EPS | 0.242 vs 0.280, −13.6% | −20% | no |
| Interim EPS (underlying basic) | 9.4p vs 11.2p, **−16.1%**, H1 to 2026-06-30, published 2026-07-29. Citation: "Adjusted Underlying Basic EPS for the period fell to 9.4p (H1 2025: 11.2p) reflecting lower operating profitability together with increased interest charges" | −10% | **yes (soft)** |
| FCF | 105.8m vs 70.4m | — | no |
| Headlines | 15 scanned, none | — | no |

Data dates: statements fetched 2026-11-10 01:48 UTC. Sector Basic Materials **sound**, but 11 of 17
members (64.7%) are below their 200-day average, against a 65% line. The 126-day return is −2.7%,
and the price trigger also needs a return below −10%.

**For the owner:** this is the closest clear name in the sample. Margin down 2.2 points, annual EPS
down 13.6% and half-year EPS down 16.1%, with the company's own text citing lower operating
profitability. Only one of these crosses its line.

### C5. IMB.L — Imperial Brands (Consumer Defensive, `buy`)

Decline **clear**; no check fired.

| Check | Evidence | Threshold | Fired |
|---|---|---|---|
| Revenue | FY2025 −0.7%; prior year −0.2% | both inside the 1% tolerance | no |
| Interim revenue | not evaluable | — | — |
| Operating margin | 10.85% vs 10.96%, −0.1 pp | −3 pp | no |
| Annual EPS (diluted) | 2.493 vs 2.990, **−16.6%** | −20% | no |
| Interim EPS | not evaluable (`interim_eps_not_on_screen_row`) | — | — |
| FCF | 3,166m vs 2,894m | — | no |
| Headlines | 95 scanned, none | — | no |

Data dates: statements fetched 2026-11-09 18:06 UTC, latest fiscal year 2025 (September year end).
Sector Consumer Defensive **sound**.

### Sector inputs

FTSE sectors that hold a sampled name, from `sector_headwind_gate.json` `sectors["ftse350:<sector>"].metrics`:

| Sector | Members | Below 200-day avg | 126-day return | Declining (decline store) | Verdict |
|---|---|---|---|---|---|
| Industrials | 51 | 21/51 = 41.2% | +13.2% | 12/47 = 25.5% | sound |
| Consumer Cyclical | 45 | 12/45 = 26.7% | +21.6% | 11/43 = 25.6% | sound |
| Energy | 8 | 3/8 = 37.5% | +1.5% | **4/8 = 50.0%** | **headwind** |
| Financial Services | 49 | 21/49 = 42.9% | +8.4% | 9/43 = 20.9% | sound |
| Communication Services | 16 | 4/16 = 25.0% | +4.6% | 4/16 = 25.0% | sound |
| Basic Materials | 18 | 11/17 = 64.7% | −2.7% | 3/16 = 18.8% | sound |
| Consumer Defensive | 20 | 2/20 = 10.0% | +22.8% | 3/20 = 15.0% | sound |

Headwind lines: 65% below the average **and** a return below −10%, or 50% declining.

### Stability over the week

Across the 18 decline-store commits from 2026-11-04 to 2026-11-10, none of the ten sampled names
changed verdict on either gate. GCP.L and BT-A.L have been in the buy tier only since the 2026-11-08
screen. Two FTSE buy-tier names changed during the week, both on code changes or new statements rather
than noise. ABF.L went from `clear` to `declining` on 2026-11-05, when the half-year extract added
a half-year EPS fall (−15.4%) to its annual EPS fall. It went back to `clear` on 2026-11-08, when
the annual EPS comparison stopped firing and the half-year fall became its only soft signal. RNK.L
was `declining` for one commit on 2026-11-05 (half-year extract) and went back to `clear` 16
minutes later, after the owner's "adjusted interim EPS first" change.

## 4. Whole-universe counts

**FTSE buy tier (70 names).** Decline: 56 clear, 11 declining, 3 `insufficient_data`. Sector: 67
sound, 2 headwind (both Energy), 1 `insufficient_data`. Twelve names are flagged and 54 pass both
gates. The four `insufficient_data` names are in section 5. The decline store's FTSE buy-tier
interim coverage is 33 of 70 for revenue and 35 of 70 for EPS.

**Graduated library markets (383 buy-tier listings in 21 markets).** 335 have a decline verdict:
226 clear, 98 declining, 11 `insufficient_data`. The other 48 have no decline-store entry at all, so
they fail closed: sp500 18, euro_stoxx50 11, omxs30 9, smi 4, iseq20 2, and one each in aim,
ftse_mib, psi20 and us_adr_asia. Sector verdicts: 284 sound, 64 headwind, 35
`insufficient_data`.

| Market | Buy tier | Decline clear / declining / insufficient (in store) | Sector sound / headwind / insufficient | Regional basis | Earnings-growth fallback |
|---|---|---|---|---|---|
| ftse350 | 70 | 56 / 11 / 3 (70) | 67 / 2 / 1 | 1 | 0 |
| sp500 | 144 | 92 / 34 / 0 (126) | 105 / 16 / 23 | 0 | 144 |
| nasdaq100 | 40 | 32 / 8 / 0 (40) | 36 / 3 / 1 | 3 | 40 |
| asx200 | 35 | 21 / 9 / 5 (35) | 27 / 4 / 4 | 0 | 35 |
| hang_seng | 24 | 16 / 8 / 0 (24) | 16 / 8 / 0 | 1 | 24 |
| aim | 17 | 5 / 7 / 4 (16) | 9 / 6 / 2 | 1 | 15 |
| tsx60 | 16 | 12 / 3 / 1 (16) | 16 / 0 / 0 | 0 | 16 |
| cac40 | 14 | 9 / 5 / 0 (14) | 11 / 3 / 0 | 6 | 14 |
| euro_stoxx50 | 12 | 0 / 1 / 0 (1) | 8 / 3 / 1 | 4 | 11 |
| dax | 10 | 6 / 4 / 0 (10) | 7 / 2 / 1 | 2 | 10 |
| ftse_smallcap | 10 | 5 / 4 / 1 (10) | 6 / 1 / 3 | 0 | 8 |
| omxs30 | 10 | 0 / 1 / 0 (1) | 9 / 1 / 0 | 5 | 10 |
| aex | 9 | 6 / 3 / 0 (9) | 5 / 4 / 0 | 6 | 9 |
| ftse_mib | 9 | 6 / 2 / 0 (8) | 7 / 2 / 0 | 2 | 7 |
| sti | 7 | 5 / 2 / 0 (7) | 7 / 0 / 0 | 1 | 7 |
| atx | 6 | 3 / 3 / 0 (6) | 3 / 3 / 0 | 4 | 4 |
| us_adr_asia | 6 | 3 / 2 / 0 (5) | 4 / 2 / 0 | 1 | 6 |
| smi | 5 | 1 / 0 / 0 (1) | 4 / 1 / 0 | 1 | 5 |
| bel20 | 3 | 2 / 1 / 0 (3) | 1 / 2 / 0 | 2 | 3 |
| iseq20 | 3 | 1 / 0 / 0 (1) | 2 / 1 / 0 | 3 | 3 |
| ibex35 | 2 | 1 / 1 / 0 (2) | 1 / 1 / 0 | 1 | 2 |
| psi20 | 1 | 0 / 0 / 0 (0) | 0 / 1 / 0 | 1 | 1 |

**Known fallbacks**, all owner-approved on 2026-11-05 (fifth amendment) and recorded on every name
as signal-risk labels ([sector gate fallbacks](sector-headwind-gate.md#fallbacks-and-signal-risk)):

- **Regional sector basis.** When a market has fewer than 4 members in a sector, the sector is
  scored across its region (UK, Europe, North America, Asia-Pacific). This applies to 45 buy-tier
  listings: 27 sound, 16 headwind, 2 `insufficient_data`. FTSE uses it once, for AEP.L, and that is
  still `insufficient_data` because the UK region also has a single Agriculture/Commodities member.
- **Library earnings-growth fallback.** Library members without a decline verdict count towards
  earnings breadth through the screen's Yahoo quarterly `earnings_growth` (decline below −5%).
  This applies to 374 buy-tier listings (277 sound, 64 headwind, 33 `insufficient_data`) and to none
  in FTSE.
- **Decline-gate interim sources.** Interim revenue comes from the Yahoo quarterly series, then
  the half-year results extract. Interim EPS comes from the quarterly series, then the half-year
  extract, then filing highlights or prose, then the screen row. When none of these exists the
  check is not evaluable and the verdict rests on annual statements. That is the case for INCH.L
  (no interim EPS) and BT-A.L (neither interim figure).
- **No price-only `sound`.** A sector needs all three inputs (price breadth, trend and earnings
  breadth) to be `sound`. Price alone can make a sector `headwind` but never `sound`; without
  earnings breadth and with no trigger fired, the sector is `insufficient_data`. Across all
  markets, 116 of 212 sectors are `insufficient_data`.

Ops findings on the same refresh (`docs/data/ops_status.json`, run 2026-11-10 02:32 UTC):
"Operating-decline gate refreshed (observe)", "Sector headwind gate refreshed (observe)", "Sector
headwind gate fallback reliance (observe)", and the warning **"Sector headwind gate coverage gap"**
for Agriculture/Commodities (FTSE) and for seven library markets whose buy-tier sectors are mostly
`insufficient_data` (aex, atx, bel20, cac40, iseq20, omxs30, psi20).

## 5. Names outside the sample

Use these for an optional spot check. Verdicts are as of 2026-11-10.

| Ticker | Sector | Decline | Sector | Reasons |
|---|---|---|---|---|
| CKN.L | Industrials | declining | sound | operating_margin_drop |
| FGP.L | Industrials | declining | sound | revenue_decline, eps_decline_interim |
| MGAM.L | Industrials | declining | sound | revenue_decline, revenue_two_year_decline, eps_decline_annual |
| PPH.L | Consumer Cyclical | declining | sound | operating_margin_drop, eps_decline_annual |
| LRE.L | Financial Services | declining | sound | operating_margin_drop |
| CNA.L | Utilities | declining | sound | revenue_two_year_decline, operating_margin_drop, eps_decline_annual, fcf_sharp_fall |
| HBR.L | Energy | clear | **headwind** | sector only (see F3) |
| BWY.L | Consumer Cyclical | insufficient_data | sound | revenue and operating income missing or stale |
| KIE.L | Industrials | insufficient_data | sound | revenue and operating income missing or stale |
| POLN.L | Financial Services | insufficient_data | sound | operating income missing; no EPS comparison |
| AEP.L | Agriculture/Commodities | clear | insufficient_data | 1 sector member; regional UK basis also 1 member |

## 6. Daily refresh health since 2026-11-04

| Weekday | Gate refresh (ops-monitor) | Close refresh | Forward dry-run |
|---|---|---|---|
| Wed 11-04 | yes, 6 commits (four of that day's runs ended `failure` but still committed) | — | workflow not on main yet |
| Thu 11-05 | yes, 02:40 and 07:52, plus code-change regenerations | — | workflow landed 23:00 UTC, after the 21:30 slot; no run |
| Fri 11-06 | yes, 02:37 and 07:52 | **no**: the slot ran at 01:03 UTC on Saturday and skipped the fetch as a weekend | ran (run 42321952361, 3.5 h late) on charts ending 11-04 or earlier; 387 names `no_session_on_or_after_start` |
| Mon 11-09 | yes, 02:37 and 07:53 | yes: ran Tue 03:45 UTC, 335 charts rebuilt, `strategy_book_closes.json` first written | ran (run 42751314679, 6.2 h late) |
| Tue 11-10 | yes, 02:41 (the 07:45 run failed and committed nothing) | 21:30 slot not yet due | not yet due |

The gates also refreshed on the weekend.

**Are closes at most one session old?** On the one refresh that ran (2026-11-10 03:45 UTC), every
market's `more_than_one_session_behind` share was 0, so the "done when" line was met as written.
But the last bar on FTSE 350 and all European library charts is 2026-11-06. US charts end 2026-11-09
and Asia-Pacific charts end 2026-11-10. So Monday's bar was not fetched for London or Europe, and
the rule counts one session behind as fresh. I could not establish from the run log why Monday's
London and European bars were missing. After the Friday slot, closes were two or more sessions
behind in every market. No "Strategy book closes stale" finding could fire then, because the closes
file did not yet exist.

**Gaps found:**

1. **Friday slot lands on Saturday.** `run_close_refresh` in `strategy_book_prices.py` skips any
   `--apply` whose clock reads a weekend (`moment.weekday() >= 5`). GitHub started both runs this
   week 3.5–6 hours late. A Friday 21:30 slot that starts after midnight UTC therefore never
   refreshes Friday's closes. Once live, Friday signals would be seen on Monday night, after
   Monday's close, and would be labelled `late_signal`.
2. **Stale failure finding.** `ops_status.json` (02:32 run) still shows "Strategy book observe
   failed: missed the 2026-11-09T21:30 slot". The forward job ran 70 minutes later, and the 07:45
   ops-monitor that would have cleared the finding exited 1 without committing. Its log shows
   `overall=warn` and repeated `usage backfill resume failed … not found` lines; I did not find the
   exit cause.
3. **Late scheduler.** Both forward runs started 3.5–6 hours after 21:30 UTC. That is harmless for
   London and New York fills, which happen at the next close. But it is the cause of gap 1.

## Go-live readiness

| # | Item | State on 2026-11-10 | Needed before `forward_live` |
|---|---|---|---|
| 1 | **Gate verdicts are never in force on a forward session** | **Blocker.** The forward job builds one gate fact per name from the current stores (`_gate_for` in `strategy_book_replay.py`). Its `as_of` is the ops-monitor run date. Registration section 2 says a verdict applies only to sessions *strictly after* its `as_of` (`_gate_index`, `as_of < session`). Ops-monitor stamps the stores with today's date before the 21:30 forward slot, so no walked session ever has a gate in force. Every buy-tier row ends up `gate` with null verdicts: 410 on the committed 2026-11-10 status, and all 65 FTSE buy-tier rows the walk loaded in a local dry run. When the gate facts were back-dated to 2026-11-05 in memory, only 12 FTSE rows stayed blocked at `gate`, each with a real `declining`, `headwind` or `insufficient_data` verdict. The tests use gate stores dated before the walked sessions, so they do not catch this. | Yes. Engineering fix: give the walk dated gate history, for example the previous committed store from git or a daily dated verdict archive. Under section 10 this is a bug fix, so it is logged as a change marker on the same `registration_id`. |
| 2 | **F9 fact dated after the chart's last bar** | **Blocker while charts lag.** The F9 bind fact is dated at the market's latest completed session (`F9Fact(as_of=scored)`), and it is in force only on or before a walked session. When a chart's last bar is older than that session, as on 2026-11-10 for London and Europe, every name is blocked `f9`, even though its binds pass. With gate and F9 facts both back-dated in memory, the 2026-11-10 dry run produced 2 FTSE entries that would open (SCT.L and VLX.L, `pending_fill`), not 0. | Yes, in the same fix as item 1, or by making sure charts always reach the scored session. |
| 3 | Friday slot weekend skip (gap 1) | Open | Strongly advised: otherwise Friday signals are `late_signal` |
| 4 | PR [#1346](https://github.com/jamiefuller320/value_investor/pull/1346), `trend_not_falling` bench seal | Open, mergeable, checks green, **not merged** | Yes. Its seal integrity rests on no forward score existing, and the first live run creates `strategy_book_observe.json`. |
| 5 | Memo spend switch-on (`cursor/memo-spend-on-567c`) | Branch pushed at `e8859d5e26`; **no PR yet, not merged**. It sets `spend_enabled: true` with an `operational_switches` record, a $40/week memo raise and a 4-weekly spend review task. | Advised. Without spend, `memo_recent` fails on most library names (148 rows in the back-dated dry run) and the memo job only logs `dry_run`. FTSE binds mostly pass today. |
| 6 | Forward store | `strategy_book_observe.json` and `strategy_book_gate_log.jsonl` do not exist. The first live `--apply` creates both. | Nothing to do |
| 7 | Seal signed | `signed: true`, `signed_at` 2026-11-05 (`registration_signed` passes) | Already true |
| 8 | Start date | No `forward_start` on the seal, so the walk starts on the `signed_at` date, **2026-11-05**. On its first live run the book re-walks 2026-11-05 to go-live. Sessions it never logged get `signal_seen_at` equal to that run's time, so any signal from those days is `late_signal` and is never filled. That can trip the "Strategy book late signals" warning (above 10%). | Owner choice: leave it, or set `forward_start` to the go-live date in the same edit. |
| 9 | Ops-monitor 07:45 failure on 2026-11-10 (gap 2) | Open | Advised, so that the go-live findings are current |

### What `forward_live` checks in code

`strategy_book_rules.forward_live()` is true only when `registration_signed()` is true and
`forward_live` is the JSON boolean `true`. The string `"true"` does not count. The forward job writes
the observe store and appends the gate log only when `forward_live` is true **and** it runs with
`--apply`. The scheduled `strategy-book-forward.yml` run uses `--apply`; a manual dispatch with
`dry_run` does not. The status file `strategy_book_forward_status.json` is written either way. No
other condition in `strategy_book_forward.py` gates the live write.

### The exact go-live change

- **Who:** the owner decides; an agent may make the edit only on the owner's recorded instruction.
  Neither job flips its own flag.
- **What:** in `docs/data/strategy_book_registration.json`, change `"forward_live": false` to
  `"forward_live": true`. Record the decision next to it, as in the memo-spend branch's
  `operational_switches` pattern: date, the owner's words, the Phase 1 outcome and a link to this
  pack. Optionally add `"forward_start": "<go-live date>"` (item 8). Sealed documents are not edited.
  The Phase 1 gate status row in the plan is updated.
- **What the first live run does:** the next weekday 21:30 UTC `strategy-book-forward.yml` run
  refreshes closes (`ftse-strategy-book-prices --apply`), then walks the book from the start date
  (`ftse-strategy-book-forward --apply`). It writes `docs/data/strategy_book_observe.json` (the first
  forward score store), starts the append-only `docs/data/strategy_book_gate_log.jsonl` with one
  session row per scored name and input hashes, and writes the status with `forward_live: true` and
  freshness `live`. Ops-monitor then drops "Strategy book forward go-live pending" and reports
  "Strategy book observe refreshed" (or "failed"). The dashboard strip shows the live state. The
  book stays observe-only (`influences_live` false); no live capital moves.

## 7. The three decisions

| Decision | What it means | What it triggers |
|---|---|---|
| **Accept** | The verdicts on the sample match the evidence well enough to gate entries. | Log the outcome in the plan's Phase 1 gate status row and on the seal. After go-live items 1, 2 and 4 are done, set `forward_live` (section 6). Gate code and thresholds stay as they are. |
| **Adjust once (logged)** | Name the threshold or thresholds and the new values, for example the two-year revenue tolerance (1%), the decline-breadth line (50%, and whether it is ≥ or >), or the soft-signal count (2). | An agent changes the constant in the gate module, its runbook and tests, regenerates both stores, and re-runs this pack's sample rule so the owner can see the effect. The adjustment is logged with old value, new value, date and reason. The gate thresholds are not in registration section 10's frozen list, and no score store has used the gates yet (the replay's full-strategy arm is empty). But section 10 says a threshold change after the first score store needs a new `registration_id`, so **the owner's note must say whether this adjustment is a change marker on `owner-strategy-book-v0` or a new id**. Go-live then proceeds as for Accept. Only one adjustment is allowed. |
| **Reject** | The gates do not identify declining names or sector trouble reliably enough. | `forward_live` stays false and the forward job keeps dry-running. The gate rules are redesigned, then a new Phase 1 review is held on the new verdicts. Because registration section 2 defines parts 2 and 3 by these gates, the redesign is likely a new `registration_id`; the owner states this in the rejection note. The archive replay and the US rehearsal are unaffected. |

Points the owner may want to weigh, all from the sample:

- **Two-year revenue rule.** It fires on small consecutive declines: INCH.L −1.8% and −1.3%, BT-A.L
  −3.5% and −2.1%. For INCH.L it overrides a +9% half-year.
- **Annual revenue in commodity names.** SHEL.L is flagged on revenue alone, while margin and EPS
  held and the latest quarter was up 36%.
- **Energy sits on the line.** 4 of 8 members are declining, exactly the ≥ 50% line, and SHEL.L is
  one of the four.
- **Funds.** GCP.L is judged by company rules on investment income.
- **Near-misses that pass.** BREE.L (margin −2.2 pp, half-year EPS −16%), IMB.L (annual EPS −16.6%)
  and DNLM.L (half-year EPS −7.3%).

## Owner decision (2026-11-10)

**Outcome: ACCEPTED with one adjustment.** Owner, verbatim: "I agree all of these: Accept both
gates as they are, keeping the 'at least 50%' line. Adjust once: funds and investment trusts get
insufficient_data from the decline gate. ... I'd argue a change marker, since it only declares that
a class of names lacks the data the gate needs. Queue for later: a minimum declining count for small
sectors; a balance-sheet check; a trust discount-to-net-asset-value lens."

**Per-name review.** The owner agreed with all ten verdicts (owner column in
[the summary](#summary)). COST.L, INCH.L, SHEL.L and BT-A.L: `declining` agreed. GCP.L: blocked, but
for the wrong reason, because it is a fund. DNLM.L, DATA.L, IGG.L, BREE.L and IMB.L: `clear` agreed.

**What changed.**

- Both gates' thresholds stay as they are, including the sector gate's `>= 50%` decline-breadth line
  (`DECLINE_BREADTH_HEADWIND = 0.50`) that SHEL.L and HBR.L sit on.
- The one allowed adjustment is **spent**. It went to a scope rule, not a threshold: funds and
  investment trusts are `insufficient_data` from the decline gate, with reason code `fund_or_trust`
  ([rule, override list and counts](operating-decline-gate.md#funds-and-investment-trusts)). The
  sector gate leaves them out of decline and earnings breadth
  ([sector gate](sector-headwind-gate.md#components-and-thresholds)). No further Phase 1 adjustment
  is available; a later threshold change is a new `registration_id`.
- Effect on the 2026-11-10 data: GCP.L is the only FTSE buy-tier name that changes
  (`declining` → `insufficient_data`; it still fails entry). Four other FTSE names change (3IN.L
  `declining`, PSH.L, BHMG.L and III.L `clear`, all now `insufficient_data`); none is in the buy tier.
  No library verdict and no sector verdict changes.
- Queued for later, each behind the next version review (machine trigger: `thickness_ready` in
  `strategy_book_forward_status.json`): L700 minimum declining-member count for small sectors, L701
  balance-sheet check in the decline gate, L702 investment-trust discount-to-NAV lens.

**Change marker or new `registration_id`?** A change marker on `owner-strategy-book-v0`:
`owner-strategy-book-v0-fund-insufficient-data-v1` in `docs/data/strategy_book_registration.json`.
The sealed text, and why it allows this:

1. Registration section 10 sends three kinds of change, after the first score store, to a new id:
   "Any threshold, the learning question, or which rule is primary", and "Adopting the alternative
   as the book". This change is none of those. No constant moves, the learning question is unchanged,
   and the primary entry and exit rules are unchanged. The frozen-parameter list in section 10 does
   not include the decline gate's internals at all.
2. Section 2 defines part 2 as "Operating-decline verdict `clear`", with "`declining` and
   `insufficient_data` both fail entry", and says "One failure, or a missing input, means the name is
   not eligible. `insufficient_data` is not a pass." A fund has no operating revenue or operating
   margin; the gate was reading investment income as revenue (GCP.L operating margin "not evaluable",
   `operating_income_missing_or_stale`). Declaring that class of names `insufficient_data` makes the
   code match the text's missing-input rule. That is section 10's first row: "A bug fix that makes the
   code match this text — A logged change marker on the same `registration_id` … The marker says what
   was wrong."
3. It only narrows entry. A fund that was `clear` now fails; a fund that was `declining` still fails.
   No name becomes eligible that was not, and every non-fund verdict is unchanged.
4. No score is rewritten. The first score store (`strategy_book_replay.json`, `first_score_store` on
   the seal) has an empty full-strategy arm because the archive has no point-in-time gate verdicts
   (section 1: "It has no point-in-time operating-decline or sector verdicts"), and no forward store
   exists. `hash_rule` ("a rule change is a new registration_id") is therefore not triggered: this is
   a data-scope fix, not a change to a rule the seal states.

The honest counter-argument: a fund that the old code scored `clear` could have entered, and now
cannot, so eligibility for that class changed. Because that change is in the fail-closed direction
the text already requires for missing inputs, and section 10 reserves new ids for thresholds,
the question and the primary rule, the marker reading holds. If the owner reads it the other way, the
marker is replaced by a new `registration_id` before go-live; the code change is the same either way.

**Not changed by this decision:** `forward_live` stays `false`. Go-live is a separate owner step
([go-live readiness](#go-live-readiness)). Since this pack was written,
[#1346](https://github.com/jamiefuller320/value_investor/pull/1346) (bench seal) and
[#1349](https://github.com/jamiefuller320/value_investor/pull/1349) (dated gate history, which fixes
go-live item 1) have merged. [#1347](https://github.com/jamiefuller320/value_investor/pull/1347)
and [#1350](https://github.com/jamiefuller320/value_investor/pull/1350) are still open.
