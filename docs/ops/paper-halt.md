# Paper halt (L564)

Observe-only rule for a paper book that has fallen too far or become too
concentrated. The action it describes is freeze new buys or flatten to cash,
then wait for a human. This version only records that the rule would fire.
Books, knobs, and orders stay as they are. There is no live broker (N13).

## Thresholds

Name, sector and currency weights use the latest marked prices in
`<track>/marked_prices.json`, written by the daily paper pass from the mark
refresh. Average cost is not a fallback: if any holding has no positive mark,
those three rules do not fire (`weight_basis` is `marks_unavailable`) and
drawdown still uses the equity curve. The equity curve is not rewritten.

| Rule | Fires when |
|------|------------|
| Drawdown | Peak-to-trough on the equity curve ≥ 20% |
| Single name | One name ≥ 40% of NAV |
| Sector | One sector ≥ 50% of NAV |
| GBP book | More than 50% of NAV is not GBP |
| Multi-currency book | One currency > 60% of NAV |

A book whose holdings are all in its reporting currency does not fire the
currency rules.

## Automation

- **Trigger:** daily ops-monitor `check_paper_halt`.
- **Store:** `docs/data/paper_halt.json` (optional ops-monitor commit).
  Marked prices sit beside each fund as `marked_prices.json`.
- **Finding:** **Paper book would halt on drawdown or concentration**.
  `auto_fixable` is false. The summary says the book was not frozen.
