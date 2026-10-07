# Paper halt (L564)

Observe-only rule for a paper book that has fallen too far or become too
concentrated. The action it describes is freeze new buys or flatten to cash,
then wait for a human. This version only records that the rule would fire.
Books, knobs, and orders stay as they are. There is no live broker (N13).

## Thresholds

Weights use average cost, because the fund file does not store a last mark
per name. Drawdown uses the equity curve, which is the marked NAV.

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
- **Finding:** **Paper book would halt on drawdown or concentration**.
  `auto_fixable` is false. The summary says the book was not frozen.
