# Paper corporate actions (L562)

A split, a cash bid, or a delisting has to hit the paper ledger on the event
date. Marks are shares times the latest price, so a name that leaves the
market otherwise stays a position forever or gets marked at a stale price.

## What the daily pass does

`run_daily_automation` calls `settle_fund_corporate_actions` after it loads
the fund and before it rebalances. It reads, in order:

1. `<track>/corporate_actions.json`
2. `docs/data/corporate_actions.json`

Missing files do nothing. The same event id is applied once
(`settled_corporate_actions` on the fund).

| Type | Effect |
|------|--------|
| `split` | Shares × `ratio`, average cost ÷ `ratio`. Cash unchanged. |
| `cash_bid` / `delisting` with `cash_per_share` > 0 | Sells the whole position at that cash amount on `effective_at`, using the book's sell cost. |
| `cash_bid` / `delisting` with no cash amount | Position stays open. `unsettled_corporate_actions` records why. |

Events after `as_of` wait. A name the book does not hold, or a position opened
after the event, is recorded as already considered and not applied later to
new shares.

The equity curve is not rewritten. Old marks stay as they were.

Splits are never inferred from a price jump. Pence/pound flips look like
splits. `events_from_split_ratios` only converts ratios the caller already
has (a committed row, or a Yahoo split series someone has chosen to accept).

## Automation

- **Trigger:** weekday paper-auto, inside `run_daily_automation`.
- **Finding:** `check_unsettled_corporate_actions` in daily ops-monitor.
  Title **Paper holding has an unsettled terminal event**. `auto_fixable` is
  false. The position is not zeroed.
- **CLI:** `PYTHONPATH=src python3 -m value_investor.corporate_actions --fund <automated_fund.json> --events <feed.json>`

Feed shape:

```json
{
  "events": [
    {
      "id": "AAA.L:2026-03-01:delisting",
      "ticker": "AAA.L",
      "type": "delisting",
      "effective_at": "2026-03-01T08:00:00+00:00",
      "cash_per_share": 1.25
    }
  ]
}
```
