# Track statistics (L529)

Observe-only instrument that answers one question for every paper learning
track: **could the measured excess be noise?**

Excess vs ^FTSE and "AI beats rules" are point estimates on a few months of
daily marks from 3-name books. Without an error bar they invite knob changes,
promotions and progress-report claims that the data cannot support.

## What it computes

Daily ops-monitor (`check_track_statistics` in `collect_ops_findings`) reads
each track's committed `automated_fund.json` equity curve under
`docs/data/paper_automation/` and writes `docs/data/track_statistics.json`.

| Field | Meaning |
|-------|---------|
| `annualized_active_return` | Mean daily active return (book − benchmark) × periods per year |
| `tracking_error` | Annualised standard deviation of active return |
| `information_ratio` | Active return ÷ tracking error |
| `t_stat` | Mean ÷ standard error of the daily active returns |
| `ci_annualized_active_return` | 90% circular block bootstrap interval (block 5, 2000 resamples) |
| `verdict` | `positive` / `negative` only when the interval excludes zero; otherwise `indistinguishable_from_noise` |
| `significant_after_correction` | \|t\| above the Bonferroni critical value across every track and pair reviewed together (family alpha 0.05) |
| `min_detectable_annual_edge` | 2 × tracking error ÷ √years — the smallest edge the current history could tell apart from zero |
| `years_to_detect_target_edge` | Years of similar marks needed to detect a 3%/yr edge at 2 standard errors |

`pairs` repeat the same statistics on the daily return difference between two
books on common dates: `ai_vs_rules` (Suite A) and `ai_fair_vs_rules_fair`
(Suite B). Tracks need ≥20 daily periods before statistics are reported.

### Method notes

- Returns come from equity-curve marks (market prices), with deposits removed,
  not from decision-review `metrics.portfolio_value`.
- Benchmark return per period uses the last close **before** each mark date
  (marks land around 09:30 London, before that day's close).
- Paper NAV does not yet credit dividends and ^FTSE is a price index (L528);
  both biases pass straight through.
- Daily marks from concentrated books carry high tracking error, so early
  `min_detectable_annual_edge` values are large. That is the point: it shows how
  far the history is from being able to confirm a realistic edge.

## Ops finding

| Title | Severity | Fires when |
|-------|----------|------------|
| **Learning-track verdict not statistically supported** | warn | `learning_tracks_review.json` has `beat_market=true` and `ai_judgment` is not `positive`, or `beat_control=true` and `ai_vs_rules` is not `positive` |
| **Track statistics observe failed** | warn | The refresh raised (bad JSON, unreadable files) |

`auto_fixable=False`. Noisy tracks alone never warn; the finding only flags a
published win the interval does not back. Response: do not cite the claim in
progress reports or analysis-review, and do not promote knobs or tracks on it.

## Drill-down

```python
from pathlib import Path
from value_investor.track_statistics import build_track_statistics

build_track_statistics(Path("docs/data/paper_automation"))
```
