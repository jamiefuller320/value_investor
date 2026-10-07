## Decision-review learning (paper-auto)

Primary loop: an **AI-judgment** paper book makes stock picks from research available
at decision time; confirmation is **excess return after costs vs the market**
(^FTSE), with a **rules** book as control. See
[`primary-learning-track.md`](primary-learning-track.md).

Screen signals stay frozen (N3). Knobs nudge slowly, and only when the book's
active return is statistically real (see
[Significance gate](#significance-gate-significance_gate_v1)).

## Knobs

| Knob | Default | Role |
|------|---------|------|
| `max_positions` | 5 | Hard sleeve cap (bounds 3–8; floor 4 on `graduated_allocation`) |
| `skip_timing_wait` | true | Drop `timing_signal=wait` from new buys |
| `min_conviction` | 0.0 | Conviction floor (bounds 0–0.6) |
| `sector_cap` | 0.30 | Max equal-weight sleeves per *known* sector |
| `exit_confirm_screens` | 2 | Hold buffer — full exit only after N consecutive rebalances outside the target set (`0` = immediate) |
| `reentry_cooldown_screens` | 1 | Rebalances to wait after a full exit before buying the same name again (`0` = off) |
| `min_rebalance_notional_gbp` | 10 | Skip trim/top-up adjustments below this GBP notional (new sleeves still open) |
| `use_adjusted_signal` | false / **true on AI track** | Gate on research overlay signal |
| `require_research_accumulate` | false / **true on AI track** | Only buy when memo verdict is accumulate |

Stored per track in `docs/data/paper_automation[/ai_judgment]/config.json`.

## Commands

```bash
# Run both tracks
ftse-paper-auto --output-dir docs/data/paper_automation --tracks all

# Review both vs market (writes learning_tracks_review.json)
ftse-decision-review --output-dir docs/data/paper_automation --tracks all

# Apply clamped updates (gate: see "Apply gate and cooldown")
ftse-decision-review --output-dir docs/data/paper_automation --tracks all --apply
```

Weekday `paper-auto.yml` seeds prior state, refreshes research overlay on
`docs/data/latest.json`, runs all three tracks, then
`ftse-decision-review --tracks all --apply`. Thin history, or a result that
does not pass the significance gate, stays propose-only.

**Churn guards** (per-track `config.json`, not decision-review knobs yet):

- **Hold buffer** — `exit_confirm_screens` (default 2): a name must be outside the
  top-N target set for that many consecutive rebalance passes before a full exit.
- **Re-entry cooldown** — `reentry_cooldown_screens` (default 1): after a full exit,
  the same ticker cannot be bought until the cooldown elapses.
- **Dust guard** — `min_rebalance_notional_gbp` (default £10): skip tiny trim/top-up
  trades; prevents same-pass sell-then-buy on rounding noise.
- **Same-day idempotency** — each track rebalances at most once per London trading
  day unless `--force` is passed (guards against duplicate workflow dispatches).

State: `automated_fund.json` → `rebalance_state` (`exit_streak`, `reentry_cooldown`).

Deterministic rollup: `learning_tracks_churn_health.json` (refreshed after
`ftse-decision-review --tracks all`). Optional agent synthesis:
[`paper-learning-review.md`](paper-learning-review.md) (`review_policy.json` kill switch).

Post-exit shadow cohorts (`exit_shadow.json`, `exit_shadow_review.json`) score
1/4/8/12-week paths after full sells. Observe-only for now — grace knob
auto-tune is deferred until closed cohorts thicken (see `learning_tracks_exit_shadow.json`).

## Artifacts

- `learning_tracks_summary.json` / `learning_tracks_review.json` — dual-track rollup
- `decision_review.json` — per-track metrics, proposed changes, reasons
- `decision_review_history.json` — per track: the last 52 reviews, plus the
  first-ever row (inception `knobs_before`) and every applied knob change, so
  rebalance-log replay keeps the full knob timeline (`retain_review_history`)
- `knob_epoch.json` — active performance baseline after the latest knob apply
- `knob_epochs.json` — history of knob-epoch snapshots (last 52)
- `proposal_basis.json` — measurement epoch for FTSE knob proposals (total return vs `FTAL.L`)
- `rebalance_log.json` — append-only decision log (candidates, knobs, trades per pass)

## Knob epochs

When `ftse-decision-review --apply` writes a knob change, the track starts a
**fresh performance epoch**: NAV at apply time becomes the baseline, and
`metrics.epoch` in `decision_review.json` reports return, cost drag, and excess
vs ^FTSE **since that apply only**. Lifetime `metrics.total_return` remains for
context; proposal heuristics switch to epoch metrics once the post-apply window
has ≥2 equity marks and ≥1 trade.

Existing tracks backfill the active epoch from the last applied row in
`decision_review_history.json` on the next review (marked `seeded_from_history`).

## Apply gate and cooldown

| Track state | Evidence used | Apply allowed when |
|-------------|---------------|--------------------|
| No knob epoch yet (cold start) | Lifetime metrics | ≥4 equity marks and ≥2 trades |
| Knob epoch exists | Epoch metrics only | ≥2 epoch marks, ≥1 epoch trade **and** epoch age ≥ `MIN_EPOCH_DAYS` (28) |

Once an epoch exists, a thin or young epoch **never** falls back to lifetime
metrics. Before this gate, the day after each apply the new epoch had <2 marks,
the review fell back to lifetime cost drag (monotone non-decreasing), and the
same rule re-fired daily: `ai_judgment` raised `min_conviction` 15 times in 16
days (11–26 Aug 2026) to its 0.6 bound with `max_positions` at the floor of 3.
Proposals are still written during cooldown (`note` reports days remaining) but
are not applied.

`epoch.age_days` is published in `metrics.epoch`.

## Proposal basis (total return vs All-Share)

FTSE books (`^FTSE` or `FTAL.L`) open `proposal_basis.json` on the first review that fetches a benchmark. From `started_at`, knob proposals use total-return excess versus `FTAL.L` (equity-curve marks plus dividend credits), not price excess versus `^FTSE`.

`metrics.excess_after_costs` stays the price-only figure, including history already written. `metrics.proposal` records the basis, the total-return excess, and the price excess it did not use. A window with fewer than two marks fails closed: excess rules see no excess, so a weak price figure cannot shrink the book. Cost and sector rules still use the reviewed book. Non-FTSE shards keep price excess until they have a local total-return proxy.

This measurement epoch does not reset knobs and is not a `knob_epoch`.

### Significance gate (`significance_gate_v1`)

The thresholds above (excess beyond ±2%, cost drag, cash) decide **what** to
propose. Since 2026-10-06 a second gate decides **whether** to apply it: the
book's annualised active return vs its benchmark must be statistically
distinguishable from zero. Before this, a few weeks of noise could move knobs:
`graduated_allocation` applied 16 knob changes between 10 Sep and 5 Oct 2026.

`significance_gate()` in `src/value_investor/decision_review.py` reads
`docs/data/track_statistics.json` (daily ops-monitor, see
[`track-statistics.md`](track-statistics.md)) and opens only when **all** hold:

- the file exists, has `updated_at` and is at most 4 days old;
- its `benchmark_ticker` matches the book's (market shards reuse FTSE track ids);
- the book has `status: ok` (≥20 daily periods);
- the verdict is `positive` or `negative` (90% block-bootstrap interval on
  annualised active return excludes zero).

Otherwise the review is written with `note: "Proposal only — significance gate
closed: …"`, `config.json` is untouched and no knob epoch starts. **`--force`
does not bypass the gate** (it only relaxes the history-thickness minimums).
Frozen labs and shadows are skipped before the gate is consulted.

Every `decision_review.json` / history row carries `apply_policy` and the
`significance_gate` record (verdict, interval, statistics timestamp, reason);
`learning_tracks_review.json` carries `apply_policy`. The gate uses the
uncorrected 90% verdict, not the Bonferroni `significant_after_correction` flag.
In practice it holds knobs still for months; that is intended. A book whose
active return is noise has nothing to learn from yet.

**History marker.** The switch is recorded in
`docs/data/paper_automation/assessment_model.json` → `policy_changes`
(`id: significance_gate_v1`, `effective_at`, `history_note`, and a per-track
`audit` of legacy applies) and surfaced on the scoreboard
(`assessment_scoreboard.json` → `policy_changes`). Knob epochs started before
`effective_at` were applied under the legacy rule; their returns are not
evidence for the knobs they set. History is not rewritten. The primary
(`ai_judgment_fair`) and control (`buy_tier_level`) never had a legacy apply,
so the primary-vs-control comparison is unaffected. Twin comparisons
(`parent_knobs_changed`) stay clean because the parent can only move on a
significant result.

### Saturated knobs

When a proposal rule still fires but the knob already sits at its clamp bound,
the review records it in `saturated_knobs` (knob, pressure direction, bound,
trigger) and appends a reason line. Frozen labs/shadows never report saturation.
Daily ops-monitor raises **Decision-review knobs saturated at bounds** only for
books decision-review can tune: not frozen in `assessment_model.json` and not a
fixed-knob lab (calibration/exclusion shadow, cohort lab such as the control
`buy_tier_level`, or churn-policy twin). The finding is a warn,
`auto_fixable=False`) — the driver is outside the knob's reach (for example the
3% stress cost model or rank-flip churn), so the fix is a policy change or a new
cold-start epoch, not another knob step.

Track-sync floors are clamp bounds too. Paper-auto track sync holds
`graduated_allocation` at `max_positions` ≥ `GRADUATED_ALLOCATION_MIN_POSITIONS`
(4), so decision-review clamps to the same floor (`max_positions_bounds_for`).
Before this, the review applied 3 every weekday, the next sync reset it to 4,
and each no-op apply restarted the knob epoch.

## Counterfactual preview

When a review proposes knob changes, `counterfactual_preview` estimates lifetime
cost impact if `max_positions` / `sector_cap` had applied from the first trade
(lightweight trade replay — no archived screen snapshots). Full P&L replay
including `min_conviction`, timing gates, and AI overlays needs the offline
archive lab (`offline_sim`); pass `--no-counterfactual` to skip the preview.

## Rebalance decision log

Every weekday paper-auto pass appends to `rebalance_log.json` per track:

- Screen source (`latest.json` `run_at`), active knobs, knob-epoch id
- **`screen_buy_tier`** — raw screen buy-tier names (before AI overlay gates)
- **`candidates`** — effective decision universe after overlay gates
- **`gate_excluded`** — tickers in screen buy-tier but dropped by overlay gates
- Plan preview, executed trades, NAV/cash/holdings and churn state before/after

Once a track has **≥2 acted log entries**, decision-review counterfactuals
graduate to **log replay** (`scope: rebalance_log_replay`) — re-running
`select_automated_targets` / rebalance on the shadow fund with proposed knobs.
When `screen_buy_tier` is logged, replay can widen the pool to raw screen
buy-tier names when AI overlay gates are counterfactually toggled.

Manual replay:

```bash
ftse-rebalance-log summary --output-dir docs/data/paper_automation/ai_judgment
ftse-rebalance-log replay --output-dir docs/data/paper_automation/ai_judgment \
  --max-positions 3 --min-conviction 0.05 --json
# AI-gate counterfactual (needs screen_buy_tier on log entries):
ftse-rebalance-log replay --output-dir docs/data/paper_automation/ai_judgment \
  --use-raw-signal --no-research-accumulate --json
```

### Pre-logging backfill

Tracks that traded before logging existed can be bootstrapped from trade history
+ nearest daily archive:

```bash
python3 scripts/bootstrap_rebalance_log.py --tracks rules
# AI-judgment (PIT research overlay via get_research_as_of):
python3 scripts/bootstrap_rebalance_log.py --tracks ai_judgment --overwrite
# or all tracks with trades:
python3 scripts/bootstrap_rebalance_log.py --tracks all --overwrite
```

Entries are marked `bootstrapped: true`. Rules tracks join archives only. AI
tracks with `use_adjusted_signal` / `require_research_accumulate` also apply
point-in-time research (`bootstrap_source=trades+archives+pit_research`) so
`adjusted_signal` / `gate_excluded` match what the overlay knew that day. Later
memo revisions must not leak into earlier passes.

### Archive → history backfill

Extend offline sim / backtest depth from dated dashboard archives:

```bash
ftse-archive-history --data-dir docs/data
ftse-sim --output-dir docs/data --grace-sweep 4,6,8
```

Skips archive dates that already have a `history/run_*.json.gz` for that calendar day.

Pre-logging trade history still needs the archive lab (L111) for full inception replay.

## Safety

- Steps are small (±1 position, ±0.05 conviction/sector).
- Applies need a statistically real active return (`significance_gate_v1`).
- No screen-signal or model-weight edits (those stay in archive weight learning).
- Evolutionary genomes (L2) wait until this loop has thicker history.
- Do not promote AI gates to live capital until the primary track shows persistent
  excess vs market and vs the rules control.
