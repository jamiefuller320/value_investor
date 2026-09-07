# Buy-tier cohort labs

Two complementary experiments for an **unfiltered buy-tier book**:

| Lab | Where | First action | Entry rule |
|-----|-------|--------------|------------|
| **Level book** (`buy_tier_level`) | Live weekday paper-auto, Suite B | Monday cold start (empty cash → first fills) | Hold every raw-screen `buy` / `strong_buy` name |
| **Cross book** (`buy_cross_archive`) | Sunday archive replay only | Week 0 is cash (no prior → no crosses) | Buy only names that *newly enter* buy-tier vs the prior weekly snapshot |

Neither is a promotion gate. The 3-slot Suite A primary and Suite B fair twins stay as they are. Do **not** spawn a live buy-cross book from this archive (sparse historic crossings).

## Level book (live, Monday)

- Directory: `docs/data/paper_automation/buy_tier_level/`
- Costs: T212-shaped Suite B (`buy_cost_pct=0.525%`, `sell_cost_pct=0.025%`) — **not** 3% stress
- Policy: raw screen signal, `min_conviction=0`, `sector_cap=1.0` (disabled), `max_positions=120`
- Timing: `skip_timing_wait=true` (same as the rules book — `timing_signal=wait` names stay out)
- Exit buffer: 2 screens; re-entry cooldown: 1 screen
- Frozen: `is_cohort_lab=true` — decision-review `--apply` cannot retune knobs
- Suite: included in `--tracks all` and `--suite B`; excluded from `--suite A`
- Cold start: committed `config.json` only — no `automated_fund.json`. First weekday paper-auto creates the fund and is epoch-zero.

Spot-check after Monday paper-auto: holdings should cover the current buy-tier (minus timing-wait), and `rebalance_log` should have the first fill row.

## Cross book (archive only)

```bash
ftse-buy-cross-archive --output-dir docs/data
```

Walks `docs/data/history/run_*.json.gz`. Week 0 records cash. Names that were buy-tier on every snapshot (e.g. `weeks_at_signal=13`) **never enter**. Held names use the same exit buffer and costs as the level book.

The same run also scores a **level comparison** (`buy_tier_level_archive`) — buy the full buy-tier each week, including week 0 — so the two entry policies can be compared on identical history.

Sunday `analysis-review.yml` refreshes `docs/data/buy_cross_archive.json` and `docs/data/buy_cross_archive_review.json` (soft-fail).

## What still blocks arbitrary archive experiments

Recording weekly screens is enough for **counterfactuals on stored fields**. It is not enough to run “any simulation we like.” Besides calendar span, the archive cannot:

1. **Invent signals** that were not computed that week (N3: do not mutate `assign_signal()`).
2. **Replay FCF / filing / memo PIT** — `ARCHIVE_SIGNAL_FIELDS` has signal, conviction, timing, adjusted_signal, research_verdict, families, trade_plan. Not FCF basis, filing figures, or memo bodies.
3. **Use fill prices** — marks are snapshot prints, not broker fills; there is no daily/intraday path.
4. **Score AI policy beyond recorded overlay** — `adjusted_signal` / `research_verdict` only when present on that snapshot.
5. **Reuse 3-name `rebalance_log` as a 61-name cohort** — knob replay follows tracks that actually traded.
6. **Treat exclusion-universe EW as a live book** — that lab is gross of costs and has no lifecycle. This lab adds T212 + hold buffer; other cost models need an explicit stamp.
7. **Close live overlays on archive near-misses** — exit-shadow / hypothesis / entry-DCA closed cohorts are live-track only.

So: we can replay *policies that consume archived weekly fields* plus an explicit cost/lifecycle model. We cannot replay “what if company FCF” or “what if we had computed a different screen that week.”

## Commands

```bash
# Live level book (weekday CI uses --tracks all)
ftse-paper-auto --output-dir docs/data/paper_automation --reports docs/data/latest.json --tracks buy_tier_level

# Archive cross + level comparison
ftse-buy-cross-archive --output-dir docs/data
```

See also: [primary-learning-track.md](primary-learning-track.md), [exclusion-universe-archive-sim.md](exclusion-universe-archive-sim.md), [market-trading-costs.md](market-trading-costs.md).
