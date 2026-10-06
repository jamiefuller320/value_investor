# Trade-plan target spread (buy → sell)

Chart and paper **tactical take-profit** levels must clear enough upside that a
filled tactical buy is worth the friction and stop risk — not just the next MA.

## Problem

`compute_trade_plan` previously set take-profit to **SMA50 whenever price was
below it**. On many buy-tier charts that put the green Target line only a few
percent above the tactical buy, often near **1:1 reward:risk**. Under Suite A
**~6% round-trip** stress that is break-even (or worse) before any edge.

Post-exit path monitoring can still teach us during the experiment phase; the
**stated target** on charts / decision packs should still be economically
sensible.

## Floors (L5 `TradePlanConfig`)

Take-profit is `max` of:

| Floor | Default idea |
|-------|----------------|
| `tactical_target_above_limit` | ≥10% above tactical buy |
| `tactical_target_above_spot` | ≥8% above last close |
| Cost + edge | `limit × (1 + assumed_round_trip_cost_pct + min_net_edge_pct)` — default 6% RT + 4% net |
| `min_reward_risk_ratio` | ≥1.5× distance from buy to stop |
| SMA50 (optional) | Only a **candidate** when price < SMA50; never a tight override |

### Market fair round trip (L405)

Callers that pass no config get `trade_plan_config_for_market(market_id)`. Its cost
floor uses the market's fair round trip from
[`market_trading_costs`](market-trading-costs.md): FTSE 350 about 0.55% (stamp duty
plus spread), and about 0.35% for non-UK markets (FX plus spread). The screen passes its
universe, charts pass their `market`, and paper-auto defaults to `ftse350`. An explicit
`TradePlanConfig()` keeps the legacy 6% stress round trip.

**No stated target moved.** The stress floor (6% round trip + 4% edge = 10%) equals the
10%-above-buy floor, so it never set a target on its own. The fair cost floor (about
4.5%) is lower again. Targets are still set by the structural floors
(`tactical_target_above_limit`, `tactical_target_above_spot`, reward:risk). Lowering
those changes take-profit levels. Those levels feed sell urgency in
`capital_allocation`, so the live books would change. That needs a twin or a new
epoch, not a config edit.

## Code

- `value_investor.technical_analysis.minimum_tactical_take_profit`
- `value_investor.technical_analysis.compute_trade_plan`

Charts read these levels via `price_charts.levels_from_trade_plan` (`take_profit`
/ `tactical_limit`).

## Related

- [market-trading-costs.md](market-trading-costs.md) — Suite A stress vs Suite B fair
- [chart-outcome-review.md](chart-outcome-review.md) — frozen initial levels / post-entry path
- [primary-learning-track.md](primary-learning-track.md) — technical track uses trade-plan stops/targets
