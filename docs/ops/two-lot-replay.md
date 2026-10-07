# Two-lot retention replay

Observe-only instrument for one learning question:

**On the wide fair-cost buy-tier book, after costs, does keeping a core lot
and recycling only a tactical slice beat selling the whole position when a
name leaves the buy tier?**

`buy_tier_level` holds one lot per name and sells all of it after
`exit_confirm_screens` outside the target set (live value: 2). The trade plan
still describes a core of about 65% and a tactical slice. This replay is the
test of that split. It does not change the book, its knobs, or any fill.

## Recording

| Question | Answer |
|----------|--------|
| Unit | One logged `buy_tier_level` rebalance pass, applied to each open lot |
| Frozen at *t* | Candidate ticker, signal, timing, price, and trade-plan stop/target when the pass logged them; the pass's exit buffer and cost knobs |
| Joined later | Yahoo closes for a held name missing from that pass's candidates |
| Never backfilled into *t* | A later thesis label, a later trade plan, or a decision to edit the live book |

## What it computes

Daily ops-monitor (`check_two_lot_replay` in `collect_ops_findings`) reads
`docs/data/paper_automation/buy_tier_level/rebalance_log.json` and writes
`docs/data/two_lot_replay.json`.

All four rules see the same passes, the same prices, and the book's fair
buy/sell costs. They are scored against `full_exit` inside this engine.
`full_exit` is trusted when it finishes within 2% of the logged end NAV.

| Rule | What is kept | What is sold |
|------|----------------|--------------|
| `full_exit` | Nothing through a rank exit | The whole position after 2 screens outside the buy tier. Equal-weight top-ups follow the live book |
| `core_kept` | 65% of each new stake. That core is not sold on rank, target, or stop | The other 35%. Sold at the logged tactical target, or 10% above the fill if the pass logged none; at the logged stop, or 8% below the fill; or on the rank exit |
| `harvest_skim` | After the first 15% gain, the unsold shares stay through later rank exits | Half of that gain, once per holding episode |
| `profit_residual` | After the first 15% gain (or a logged target hit that is actually in profit), only the gain remains as core | Shares worth the cost basis. Until that donation, a rank exit still sells the whole tactical lot |

Cash from a tactical sale is not put back into the same name on that pass.
The tactical sleeve reopens on a later pass at or below 95% of the sale
price, or when the name leaves the buy tier and comes back. The £10 minimum
applies to a sleeve's total buy, not to each lot, so a wide book's small
line can still be split.

There is no thesis-break flag on the log, so a core lot is not sold inside
this replay. Marks are price-only. Dividends are not credited.

## Ops finding

| Title | Severity | Fires when |
|-------|----------|------------|
| **Two-lot retention beats full exit in replay** | warn | `status` is `ok` and the best retention rule beats `full_exit` by ≥1 percentage point |
| **Two-lot replay observe failed** | warn | The refresh raised |

`auto_fixable=False`. A positive delta is a hypothesis. It does not edit
`buy_tier_level` and it does not open a live twin. The hold-buffer and
harvest twins are separate questions on the 3-name primary.

## Limits

The current window is a few weeks. `core_kept` can show a small gap just
because tactical stops fired, not because a multi-year value stake has been
earned. `profit_residual` only donates after a name is already up 15%, so on
a flat window it stays close to `full_exit`.
