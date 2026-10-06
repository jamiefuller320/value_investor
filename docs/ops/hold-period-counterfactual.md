# Hold-period counterfactual (L531)

Observe-only instrument for one learning question:
**would holding positions longer (fewer rank-driven "left target set" exits)
improve after-cost return on the live books?**

Closed holdings on the headline tracks last a median of about 4 days. Value
premia are expected to accrue over years. The hold-buffer knob is
`exit_confirm_screens`: the number of consecutive weekday screens a holding must
sit outside the target set before it is sold (live value: 2). There is no
separate minimum-hold knob.

This instrument never changes books, knobs, gates or published metrics.

## What it computes

Daily ops-monitor (`check_hold_period_counterfactual` in `collect_ops_findings`)
reads each headline track's `rebalance_log.json` and `automated_fund.json`
under `docs/data/paper_automation/` and writes
`docs/data/hold_period_counterfactual.json`.

For `ai_judgment`, `rules`, `ai_judgment_fair` and `rules_fair`:

| Field | Meaning |
|-------|---------|
| `realised` | From live fund trades: FIFO closed-lot `median_hold_days`, `p75_hold_days`, `max_hold_days`, and `annualised_sell_turnover` (sell gross ÷ average NAV, annualised) |
| `window` | Replay window: `from`/`to`, `passes`, `skipped_passes` (log passes dropped from the start) and `fidelity_gap` (baseline replay NAV minus logged end NAV, ÷ start NAV) |
| `baseline` | Replay with the logged knobs of each pass: return, trade count, cost drag |
| `variants` | Same replay with `exit_confirm_screens` 5, 10 and 20: return, `delta_vs_baseline`, trade count, cost drag |
| `best_variant` | Variant with the highest `delta_vs_baseline` |
| `status` | `ok`, or `unreliable` with a `reason` when no faithful window exists |

### Fidelity gate

A replay is only scored when its baseline reproduces the live book. The window
starts at the earliest acted pass whose baseline replay (logged per-pass
`max_positions`, conviction, sector and timing knobs) ends within **1%** of the
last logged `nav_after`, with at least **8** passes left. This drops:

- **Log holes**: trades that happened between logged passes. Example: `rules`
  traded on 2026-08-10, -12, -14 and -18 without log entries.
- **Seed bursts**: warm-start passes logged at one timestamp with a reset
  exit-streak state. Example: the first `ai_judgment` passes on 2026-08-18.

Variants are scored against the **baseline replay**, not the live book, so both
sides share the same prices.

### Method notes

- Replays only see names in each pass's logged candidates. A held name missing
  from a pass is marked at its last logged price scaled by the Yahoo close ratio
  (`held_price_fills`); without a ratio it falls back to average cost
  (`held_price_avg_cost_fallbacks`).
- `exit_confirm_screens` 20 is longer than most windows, so it reads as
  "almost never exit on rank".
- Windows are weeks long on 3-name books (see [track statistics](track-statistics.md),
  L529). A positive delta is a hypothesis for a cold-start twin, not adoption
  evidence.
- The replay depends on the phantom-cash fix in `rebalance_log` (L540). Earlier
  replays of fully invested books were not trustworthy.

## Ops finding

| Title | Severity | Fires when |
|-------|----------|------------|
| **Longer holds beat live exit buffer in replay** | warn | For a track with `status: ok`, the best variant beats the baseline replay by ≥1 percentage point |
| **Hold-period counterfactual observe failed** | warn | The refresh raised (bad JSON, unreadable files) |

`auto_fixable=False`. Response: do **not** edit `exit_confirm_screens` on a live
book. If the finding persists on the fair-cost books across several weeks, the
next step is a cold-start hold-buffer twin with a frozen epoch ("twins over
edits"). Decision-review knob proposals stay as they are.
