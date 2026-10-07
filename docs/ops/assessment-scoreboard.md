# Assessment scoreboard

One table for the paper learning tracks, on one fair cost basis. It replaces
reading Suite A (3% stress) and Suite B (fair T212) side by side.

Learning question: **is the primary book beating the market, and is its
filter adding anything over the unfiltered buy tier?**

The tracks it ranks come from the assessment model
(`docs/data/paper_automation/assessment_model.json`, see
[`experiment-assessment.md`](experiment-assessment.md)): one **primary**
(`ai_judgment_fair`), one **control** (`buy_tier_level`), any other active
tracks, and the frozen books with their final record.

## Columns

| Field | Source | Meaning |
|-------|--------|---------|
| `total_return` / `benchmark_total_return` / `excess_total_return` | [`total_return_view.json`](total-return-view.md) | Dividends credited, vs `FTAL.L` total return. Fair books start on their clean epoch (first trade after early stress-cost fills). |
| `statistics.ci90` / `verdict` / `years_to_detect_3pct_edge` | [`track_statistics.json`](track-statistics.md) | 90% bootstrap interval on annualised active return (price basis). The interval is the uncertainty band; the total-return columns are the level. |
| `excess_total_return_at_stress_cost` | trade log in each book's `automated_fund.json` | Every buy and sell in the window re-priced at 3% per side, as a share of starting capital. Shows how much of the excess survives a harsh cost world without running duplicate stress books. |
| `ai_gate` | track `config.json` + [`screen_premise_backtest.json`](screen-premise-backtest.md) | Whether the AI research gate is on and how much of the buy tier it lets through. `binds: false` means the gate passes ≥80% of the buy tier, so the "AI" book is mostly the buy tier. |
| `primary_vs_control` | `total_return_view.json` | Primary minus control total return on their common window. |

`headline` feeds the dashboard progress headline (`project_progress.py`):
there is no hard-coded "ahead of schedule" or "AI beats rules" claim; stage
2b is only marked complete when the primary's verdict is `positive`.

## Twins

A twin is a cold-start book that copies an active parent's knobs and varies
exactly one. It is registered under `twins` in `assessment_model.json` with the
parent's knobs at start, the learning question and the readiness gate. Twins
are churn-policy twins, so decision-review `--apply` never tunes them, and a
frozen parent cannot get a new twin.

The scoreboard's `twins` list compares each twin with its parent on the days
both books were marked since the twin began (flow-adjusted price NAV):
`twin_return`, `parent_return`, `difference`. `parent_knobs_changed` lists any
parent knob that differs from the recorded start values; a non-empty list
means the comparison is confounded by parent tuning.

### Hold-buffer twin (L541)

`ai_judgment_hold5_fair`, started 2026-10-06 from fresh capital: the primary
`ai_judgment_fair` with `exit_confirm_screens` 5 instead of 2, fair costs.

- **Question:** does holding through 5 confirming screens beat the primary on
  total return? The L531 replay (`hold_period_counterfactual.json`) put it at
  +5.8pp over 19 passes, mostly from avoided rank-flip exits.
- **Gate:** promote the longer buffer to the primary only if the twin leads
  over ≥26 weekly screens with the parent's knobs unchanged and the
  twin-minus-parent interval excludes zero. Otherwise freeze the twin. Human
  Sunday card `sunday-hold-buffer-twin`.
- Spawned with `ftse-trading-costs spawn-hold-buffer-twin` (idempotent).

### Graduated-allocation twin

`ai_judgment_graduated_fair`, started 2026-10-06 from fresh capital: the
primary `ai_judgment_fair` with `use_graduated_allocation` on (trade-plan
starter sizing + harvest skims via `run_graduated_rebalance`), fair costs. Every
other knob, including `max_positions` 3 and the AI gates, matches the primary.

- **Question:** does graduated sizing beat the primary's equal-weight sizing on
  total return at fair costs? The older `graduated_allocation` book could not
  answer this (rules screen, 3% stress costs, outside the assessment model);
  it was frozen on 2026-10-07 with this twin as `superseded_by`.
- **Gate:** same as the hold-buffer twin (≥26 weekly screens, parent knobs
  unchanged, interval excludes zero; otherwise freeze). Human Sunday card
  `sunday-graduated-twin`.
- Entry-DCA execute is still wired to `graduated_allocation`, which is frozen,
  so execute stays blocked. When N135's trigger is met, repoint it at this twin.
- Spawned with `ftse-trading-costs spawn-graduated-twin` (idempotent).

## Automation

- **Trigger:** daily ops-monitor `check_assessment_scoreboard` (runs after
  the total-return, track-statistics and screen-premise checks).
- **Store:** `docs/data/assessment_scoreboard.json`, committed by
  `scripts/gha_commit_ops_monitor.sh` (optional observe store).
- **Finding:** **Primary book trails its control on total return** (warn,
  `paper`, `auto_fixable=False`) when the primary is ≥5pp behind the control
  on the common window. **Assessment scoreboard observe failed** if the build
  raises.
- **CLI:** none; read the JSON or the dashboard.

## What not to do from this

- Do not switch the primary, edit knobs or unfreeze a book from one finding.
  A primary/control gap is a prompt to look at the gate and screen-premise
  spreads, not an apply step.
- Do not read a `positive` verdict on a few months of 3-name marks as
  adoption truth; check `years_to_detect_3pct_edge` and the cross-sectional
  [`screen-premise-backtest.md`](screen-premise-backtest.md) first.
