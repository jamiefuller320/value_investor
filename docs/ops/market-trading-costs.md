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

## Test and adoption strategy (dual suite)

Fair costs change the **performance narrative**, not the value of a harsh churn lab.
Run **two suites with different jobs** — do not merge them into one muddy primary.

### Suite A — Stress / defensive lab (keep running)

| | |
|--|--|
| **Where** | Live FTSE primary + control (`ai_judgment`, `rules`, existing calibrated/exclusion shadows) at **3% per side** |
| **Job** | Find the best **conservative / low-churn** policy: survive harsh friction, keep cost_drag and trade_count in check |
| **Optimize for** | Cost drag, trade count, hold stability, epoch knob discipline |
| **Do not use for** | Absolute “beat ^FTSE after costs” promotion truth (the hurdle is artificially brutal) |

Keep weekday paper-auto and decision-review on this suite uninterrupted. Stress remains a **filter**: knobs that only “win” by churning will still look bad here.

### Suite B — Fair / performance lab (start warm)

| | |
|--|--|
| **Where** | Small new parallel books (prefer **1–2** fair-cost shadows first: AI + rules), warm-started from parent `rebalance_log` like calibration shadows |
| **Job** | Measure **deployable** excess vs ^FTSE / control under T212-shaped buy/sell |
| **Stamp** | `buy_cost_pct` / `sell_cost_pct` / symmetric proxy from `ftse-trading-costs` (UK table for FTSE) |
| **Optimize for** | Excess after fair costs; secondary: still-reasonable churn |

Use the existing warm-start pattern (`ftse-knob-calibrate warm-start-shadow`) so forward endurance is clean — do **not** re-warm every weekday.

### How the two interact

```text
Stress lab (A) ──discovers──▶ conservative knob candidates
                                    │
                                    ▼
Fair lab (B) ──validates──▶ promotion / adoption truth vs ^FTSE
                                    │
                                    ▼
Primary flip (N48) only after B endures — never silent config rewrite
```

1. **Discover** under stress (A): raise conviction, exit confirms, grace/exclusion that cut churn.
2. **Validate** under fair (B): same knobs on fair-cost warm-start books; require beat market *and* beat fair-cost rules control.
3. **Promote** to primary only when B clears human gates — primary can stay on stress until then, or flip together once B is trusted (**N48**).
4. **Observe sims / euro_depth shards** already default to fair — treat those as Suite B breadth, not a second stress lab (override with `--trade-cost 0.03` only when deliberately stress-testing a market).

### Capacity guard

Learning-director vision caps open experiments (~5). Fair lab should start as **two books**, not a fork of every shadow. Existing calibrated shadows stay on stress with primary until Suite B proves useful.

### Near-term actions

| Priority | Action |
|----------|--------|
| Now | Keep Suite A as-is; use `ftse-trading-costs assess` on Sunday for a first-order fair read of primary |
| Next | Implement Suite B warm-start shadows with fair costs stamped (parked as deferred until built) |
| Later | Flip primary off 3% only after B has a thick forward window (**N48**) |

See also: [`knob-calibration.md`](knob-calibration.md) (warm-start),
[`primary-learning-track.md`](primary-learning-track.md),
[`market-sharded-learning.md`](market-sharded-learning.md).
