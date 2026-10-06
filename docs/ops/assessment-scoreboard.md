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
