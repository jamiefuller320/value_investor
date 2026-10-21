# N215 soft-veto → MONITOR reentry observe (sealed)

**registration_id:** `n215-reentry-warn-r1-v0`  
**pair_id:** `WARN+_R1`  
**deferred:** N215  
**Mode:** observe-only — never writes strand A / paper books, knobs, or `decision-review --apply`

## Learning question

Among soft-vetoed (**WARN+**) sealed **N200** names that later became **large winners** under sealed baseline fair-cost: how often would frozen MONITOR rule **R1** (breakout-wait; **R5**=40 sessions / **R6**=−15% DD) have **re-admitted** before opportunity expired — vs **never** (timeout / worsen)? Companion: path-cost Δ vs sealed baseline on recovered names; abandon rate on WARN+ deep losers. Labels only — **no live gate**.

## Frozen pair (pre-registered)

| Piece | Pin |
|---|---|
| Band gate | WARN+ (soft band ∈ {WARN, SOFT_VETO, HARD_CANDIDATE}; soft recipe `n215-soft-score-recipe-v0`) |
| Reentry | **R1** breakout-wait: close > pre-`t0` lookback max close by ≥ **1%** |
| Abandon | **R5** timeout **40** trading sessions; **R6** worsen ≤ **−15%** from `t0` close |
| Point-in-time | Forward walk uses bars with `date ≤ t` at each step |
| Fail-closed | Missing chart / no forward bars → `unevaluable` (not counted as never) |
| Companion cell | Same R pins on **SOFT_VETO+** subset (report-only) |

Do **not** retune pins on this cohort for admission claims. Layer B separate from soft-band Layer A — no bundle-admit.

## When it runs

| Trigger | Schedule |
|---|---|
| **Daily ops-monitor** | `check_n215_reentry_observe` refreshes store from N200 sealed store + soft-band scores + charts |
| Manual | `ftse-n215-reentry --output-dir docs/data` |

## Artifacts

| Path | Role |
|---|---|
| `docs/data/n215_reentry_registration.json` | Frozen seal / pair record |
| `docs/data/n215_reentry_observe.json` | Per-episode monitor labels + re-admit/never rollup |
| This doc | Runbook |

Stores commit via ops-monitor `GHA_COMMIT_OPTIONAL`.

## Constraints

- No live MONITOR delay / reentry on fills.
- Progressive admission still required before any future Layer B influence.
- Soft-band entry catch/miss remains co-equal LQ-A; this instrument is LQ-B only.
- `still_monitor_eop` (chart ended before 40d without signal) is not counted in never rate.

## Related

- Soft-band harness: [n215-technical-veto-observe.md](n215-technical-veto-observe.md)
- Project store: `technical-veto-reentry-lq.md`, `technical-veto-monitor-reentry.md`
- Park: **N215**
