# N215 soft-veto → MONITOR reentry observe (sealed)

**registration_id:** `n215-reentry-warn-r1-v0`  
**pair_id:** `WARN+_R1`  
**deferred:** N215  
**Mode:** observe-only — never writes strand A / paper books, knobs, or `decision-review --apply`

## Learning question

Among soft-vetoed (**WARN+**) sealed **N200** names that later became **large winners** under sealed baseline fair-cost: how often would frozen MONITOR rule **R1** (breakout-wait; **R5**=40 sessions / **R6**=−15% DD) have **re-admitted** before opportunity expired — vs **never** (timeout / worsen)? Companion: path-cost Δ vs sealed baseline on recovered names; abandon rate on WARN+ deep losers. Labels only — **no live gate**.

**Thickened (same frozen pair):** also report full WARN+ gated terminal outcome mix, positive-FC re-admit (beyond ≥+10% large cell), and **N206** holdout (report-only; never tune).

## Frozen pair (pre-registered)

| Piece | Pin |
|---|---|
| Band gate | WARN+ (soft band ∈ {WARN, SOFT_VETO, HARD_CANDIDATE}; soft recipe `n215-soft-score-recipe-v0`) |
| Reentry | **R1** breakout-wait: close > pre-`t0` lookback max close by ≥ **1%** |
| Abandon | **R5** timeout **40** trading sessions; **R6** worsen ≤ **−15%** from `t0` close |
| Point-in-time | Forward walk uses bars with `date ≤ t` at each step |
| Fail-closed | Missing chart / no forward bars → `unevaluable` (not counted as never) |
| Companion cell | Same R pins on **SOFT_VETO+** subset (report-only) |
| Holdout | Same R pins on sealed **N206** closed episodes — report-only; **never tune** |

Do **not** retune pins on this cohort for admission claims. Layer B separate from soft-band Layer A — no bundle-admit.

## Clear-signal twin (design-locked companion)

| Piece | Pin |
|---|---|
| Registration | `n215-reentry-warn-r4-v0` / pair `WARN+_R4` |
| Reentry | **R4** RSI-reset: post-`t0` RSI14 ≤ **35**, then RSI14 ≥ **45** with close > **SMA20** |
| Abandon | Same **R5**=40 / **R6**=−15% as primary |
| Not | R1 thr nudge; R5 stretch; live admit from twin alone |
| Store | `clear_signal_twin` in `n215_reentry_observe.json` + `n215_reentry_twin_r4_registration.json` |
| Hurdles | Pre-registered (N200 large 3/3 · deep 4/4; N206 MU reenter + KHC/TROW abandon) |

CLI default includes twin (`--no-twin` to skip). Project store: `technical-veto-clear-signal-twin.md`.

## When it runs

| Trigger | Schedule |
|---|---|
| **Daily ops-monitor** | `check_n215_reentry_observe` refreshes store from N200 (+ N206 holdout) + soft-band scores + charts (+ R4 twin) |
| Manual | `ftse-n215-reentry --output-dir docs/data` (`--no-n206-holdout` / `--no-twin` optional) |

## Artifacts

| Path | Role |
|---|---|
| `docs/data/n215_reentry_registration.json` | Frozen R1 seal / pair record |
| `docs/data/n215_reentry_twin_r4_registration.json` | Frozen R4 twin seal |
| `docs/data/n215_reentry_observe.json` | Per-episode R1 labels + thickened rollups + `holdout_N206` + `clear_signal_twin` |
| This doc | Runbook |

Stores commit via ops-monitor `GHA_COMMIT_OPTIONAL`.

## Constraints

- No live MONITOR delay / reentry on fills.
- Progressive admission still required before any future Layer B influence.
- Soft-band entry catch/miss remains co-equal LQ-A; this instrument is LQ-B only.
- `still_monitor_eop` (chart ended before 40d without signal) is not counted in never rate.
- N206 holdout marks must not drive pin changes.

## Related

- Soft-band harness: [n215-technical-veto-observe.md](n215-technical-veto-observe.md)
- Project store: `technical-veto-reentry-lq.md`, `technical-veto-monitor-reentry.md`, `technical-veto-reentry-thickened.md`, `technical-veto-clear-signal-twin.md`
- Park: **N215**
