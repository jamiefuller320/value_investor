# Total-return view (L528 / L532 / L533)

Observe-only instrument that re-scores every paper learning track on a
total-return basis, next to the published price-only numbers. It answers:
**is the published excess the right size and sign once dividends, a matching
benchmark and stress-cost leftovers are accounted for?**

The published `excess_after_costs` in each `decision_review.json` has three
known biases:

- Paper funds do not credit dividends, which matters for a high-yield value book.
- The benchmark is `^FTSE`, a FTSE 100 **price** index, for a FTSE 350 book.
- Decision-review NAV values holdings at average cost, not market price.

Fair-cost books (`ai_judgment_fair`, `rules_fair`) also carry early trades
charged at the 3% stress rate, from before their cost model switched (L533).

This view never changes books, knobs, gates or published metrics.

## What it computes

Daily ops-monitor (`check_total_return_view` in `collect_ops_findings`) reads
each track's `automated_fund.json`, `config.json` and `decision_review.json`
under `docs/data/paper_automation/` and writes `docs/data/total_return_view.json`.

| Field | Meaning |
|-------|---------|
| `lifetime.price_return` | NAV change from equity-curve marks (market prices), deposits removed |
| `lifetime.dividends_gbp` | Dividends on shares held over each ex-date in the window, credited as cash (not reinvested) |
| `lifetime.total_return` | Price return plus dividends |
| `lifetime.benchmark_price_return` / `benchmark_total_return` | `^FTSE` / `FTAL.L` (SPDR FTSE UK All Share, accumulating) over the same window |
| `lifetime.excess_total_return` | Book total return minus `FTAL.L` |
| `published_excess_after_costs` | Copied from `decision_review.json` for comparison |
| `stress_cost_trades_until` / `clean_epoch` | Fair-cost books only: last trade charged at ≥2% and the same scores from the first mark after it |
| `pairs.primary_vs_control` | Value-beta control (L532): the primary minus the control from `assessment_model.json` (now `ai_judgment_fair` minus the unfiltered `buy_tier_level`) on their common window. Positive means the primary's filter added value beyond holding the buy tier |
| `assessed_tracks` | Primary, control and unfrozen twins. Only these raise the misstatement finding; frozen books keep their rows for the scoreboard's final records |

### Method notes

- Dividend amount = shares × paper price at the ex-date × (dividend ÷ close the
  day before ex-date). Dividend and close come from the same Yahoo row, so the
  pence/pound scaling cancels and paper prices may be in either unit.
- Shares count only when bought on an earlier day than the ex-date and not sold
  before it. Yields above 15% are skipped and listed in `dividends_skipped`.
- Benchmark windows use the last close **before** each mark date (marks land
  around 09:30 London, before that day's close).
- `FTAL.L` is an ETF proxy for the All-Share total-return index, so it carries a
  small fee drag. That drag is far smaller than the price-vs-total-return gap it
  corrects.
- Windows are a few months long, so read these alongside
  [track statistics](track-statistics.md) (L529) before drawing conclusions.

## Ops finding

| Title | Severity | Fires when |
|-------|----------|------------|
| **Price-only excess misstates track performance** | warn | For an assessed book (primary, control or an unfrozen twin; `assessed_tracks`), the published excess and the total-return excess differ in sign or by ≥5 percentage points. Fair-cost books use the clean epoch when one exists |
| **Total-return view observe failed** | warn | The refresh raised (bad JSON, unreadable files) |

`auto_fixable=False`. Response: cite the total-return figure (and the clean
epoch for fair-cost books) in progress reports and analysis-review. Do not
rewrite published metrics or knobs from this finding; switching the live
review to total return is a separate, epoch-marked change.

## Drill-down

```python
from pathlib import Path
from value_investor.total_return_view import build_total_return_view

build_total_return_view(Path("docs/data/paper_automation"))
```
