# Market trading costs (fair assumptions)

Paper learning books historically used a flat **`trade_cost_pct = 0.03`** (3% per side ≈ 6% round-trip). That is a harsh churn stress case, not broker reality for Trading 212 Invest.

This ops note documents **explicit, per-market fair friction** so observe sims, market shards, and performance assessments can use realistic rates without silently rewriting the live FTSE stress config.

## Building blocks (T212 Invest–shaped)

| Component | Rate | When |
|-----------|------|------|
| Half-spread (liquid large-caps) | ~0.025% | Each side |
| UK stamp duty (SDRT) | 0.5% | **Buys** of UK shares |
| FX conversion | ~0.15% | When GBP-funded book trades a non-GBP venue (modelled each side) |

Commission is treated as **zero** on Invest. Rates are learning assumptions — not a live brokerage quote.

## Typical fair totals

| Market | Buy | Sell | Round-trip | Notes |
|--------|-----|------|------------|-------|
| `ftse350` | ~0.525% | ~0.025% | ~0.55% | Stamp dominates; no FX |
| `sp500` / US | ~0.175% | ~0.175% | ~0.35% | FX + half-spread |
| `euro_depth` / EU | ~0.185% | ~0.185% | ~0.37% | Slightly wider half-spread + FX |

Exact figures: `ftse-trading-costs list`.

## What uses fair costs

| Surface | Behaviour |
|---------|-----------|
| Live FTSE `docs/data/paper_automation/**/config.json` | **Unchanged** — keeps 3% stress unless you edit intentionally |
| Phase 2+ market shards (`apply_shard_session_to_configs`) | Stamps `buy_cost_pct` / `sell_cost_pct` / symmetric proxy from the market table |
| Library observe sim (`ftse-library sim`) | Defaults to fair symmetric proxy; `--trade-cost` overrides |
| `ftse-trading-costs assess` | Read-only recompute of recorded trade friction under fair rates |

Paper fund execution supports asymmetric buy/sell via `buy_cost_pct` / `sell_cost_pct` on `AutomationConfig` / `PaperFundConfig` (`cost_pct_for_side`).

## Commands

```bash
# Table of assumptions
ftse-trading-costs list
ftse-trading-costs list --market ftse350 --json

# Assess live FTSE AI/rules books under fair UK costs (does not rewrite configs)
ftse-trading-costs assess --market ftse350
ftse-trading-costs assess --paper-root docs/data/paper_automation --tracks ai_judgment,rules --json

# Shard / observe paths pick fair costs automatically
ftse-library sim --markets euro_depth
ftse-library sim --markets euro_depth --trade-cost 0.03   # explicit stress override
```

## Interpreting `assess`

- **recorded_costs** — sum of stored trade `cost` fields (usually 3% stress).
- **fair_costs** — same notionals under the market table.
- **cost_drag_relief** — (recorded − fair) / contributed capital. First-order add to a previously cost-penalised total return; does **not** rebuild fills or excess vs `^FTSE`.

## Design rules

1. Do **not** flip primary FTSE learning books off 3% without an explicit human decision — keep stress and fair views separate.
2. New market shards and observe sims should use fair assumptions by default.
3. AIM stamp exemptions and per-ticker spreads are deferred; current AIM row keeps stamp on for conservatism.

See also: [`primary-learning-track.md`](primary-learning-track.md), [`market-sharded-learning.md`](market-sharded-learning.md).
