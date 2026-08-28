# Primary learning track (hands-off)

## Idea

Stock-picking decisions are made by an **AI quasi-human** policy using whatever
research/overlay is available at decision time. Confirmation is **not** a human
trade checklist — it is a performance comparison to market datums. Success =
**outperformance after costs** in that market.

## Tracks

| Track | Directory | Decision policy | Role |
|-------|-----------|-----------------|------|
| **AI judgment** *(primary)* | `docs/data/paper_automation/ai_judgment/` | `adjusted_signal` + `research_verdict=accumulate` | Learning book |
| **Technical** *(baseline)* | `docs/data/paper_automation/technical/` | Stops/targets from `trade_plan`, tactical entries | Timing/levels floor vs stock-picking |
| **Screen rules** *(control)* | `docs/data/paper_automation/` | Raw buy-tier screen signal | Baseline datum |
| **Momentum grace** *(experimental)* | `docs/data/paper_automation/momentum_grace/` | Screen rules + bounded hold on value downgrade when price trend stays strong | Exit-overlay experiment |
| **Graduated allocation** *(experimental)* | `docs/data/paper_automation/graduated_allocation/` | Screen rules + trade-plan starter sizing + harvest skims (`max_positions=4`) | Capital recycling experiment |
| **Exclusion ladder** *(experimental)* | `docs/data/paper_automation/ai_judgment_exclusion_u4/` | AI judgment + frozen archive ladder `u4` knobs (spawned shadow) | Loser-filter ladder experiment |

Both primary books use the same costs, position caps, and weekday paper-auto schedule.
Live FTSE configs keep the **3% per-side stress** cost by default; use
`ftse-trading-costs assess` for a fair T212-shaped view without rewriting books
([`market-trading-costs.md`](market-trading-costs.md)).

## Post-exit shadow learning (observe-only)

On every paper-auto run, each track records **full position sells** into a shadow cohort and
scores post-exit price paths at 1/4/8/12 weeks. Artifacts per track:

- `exit_shadow.json` — open + closed cohort records
- `exit_shadow_review.json` — aggregate verdicts by exit kind (`grace`, `screen_rotation`, …)
- `learning_tracks_exit_shadow.json` — rollup across tracks (compare grace vs rules)

Verdicts (`good_exit`, `early_exit`, `neutral`) are **not** wired to auto-tune grace knobs yet —
wait for a thicker closed cohort before promoting parameter changes.

## Exit-timing cohorts (observe-only)

On the same paper-auto pass, each track also records **hold-recovery** and **swap-rotation**
cohorts for the exit-timing research strand (P(hold→breakeven) vs P(swap→better prospect)):

- `exit_timing_cohorts.json` — open + closed episodes per track
- `exit_timing_cohorts_review.json` — readiness + summaries
- `learning_tracks_exit_timing.json` — rollup across tracks

See also [`exit-timing-cohorts.md`](exit-timing-cohorts.md) for live paper cohorts and
[`exit-timing-archive-sim.md`](exit-timing-archive-sim.md) for offline near-miss priors.

## Success datums

1. **Market:** excess return after costs vs FTSE 100 (`^FTSE`) on the primary book.
2. **Control:** primary excess should also beat the rules book on the same window
   before promoting further knobs/gates.

Human verify-before-trade packs remain useful for live capital, but they are
**not** the primary learning loop.

## Human tasks checklist

Weekly manual gates (Sunday priors review, shadow vs primary, promotion rules)
live in [`human-tasks-checklist.md`](human-tasks-checklist.md) and on the
dashboard **Automation → Human tasks** panel.

## Commands

```bash
# Run both tracks after open settle
ftse-paper-auto --output-dir docs/data/paper_automation --reports docs/data/latest.json --tracks all

# Review both vs market; apply knobs only when history is thick
ftse-decision-review --output-dir docs/data/paper_automation --tracks all --apply

# Refresh overlay + force bootstrap (weekends / testing):
python3 scripts/bootstrap_learning_loop.py
```

Weekday CI (`paper-auto.yml`) refreshes the research overlay on `docs/data/latest.json`
automatically before trading — no manual bootstrap needed.

Artifacts: `learning_tracks_summary.json`, `learning_tracks_review.json`, plus
per-track `automated_fund.json` / `decision_review.json` / `rebalance_log.json`
(append-only decision snapshots for knob counterfactual replay).

## Safety

- Does **not** rewrite base screen `assign_signal()` (N3).
- Knob updates stay small and clamped (L1).
- Evolutionary genomes (L2) wait until this loop has thick walk-forward history.
- Live broker automation stays off until the primary track shows persistent excess.
