# Hypothesis integrity (in-portfolio losers)

Observe-only strand for **hypothesis-first underwater review**. Buying value
already implies fundamental cheapness — a mark drop should first ask whether
the investment hypothesis still holds on the facts, not fire a crude stop.

## Why

| Crude stop | Hypothesis-first |
|------------|------------------|
| Price ≤ tactical stop → sell | Price drop → check screen/research facts |
| Treats every loser as a failure | Tolerates a share of intact losers |
| No feedback into selection | Loser family-fail rates feed selection feedback |
| Ignores portfolio balance | `balancing_hint` guides rotation priority |

## What runs

On every paper-auto pass (and via CLI):

```bash
ftse-hypothesis-integrity --output-dir docs/data/paper_automation --tracks all
```

Per track (`docs/data/paper_automation/<track_id>/`):

| Artifact | Role |
|----------|------|
| `hypothesis_integrity.json` | Holding thesis cards + portfolio_feedback |
| `hypothesis_integrity.md` | Human-readable summary |

Rollup: `docs/data/paper_automation/learning_tracks_hypothesis_integrity.json`

## Per-holding thesis status

| Status | Meaning | Default action |
|--------|---------|----------------|
| `intact` | Still buy-tier / cheapness / supportive research | `hold_tolerate` (deep drawdown → `watch_review`) |
| `weakening` | Left buy tier, cheapness lost while still buy, weak conviction, etc. | `watch_review` |
| `broken` | Avoid signal, broken research verdict, cheapness lost + not buy | `exit_candidate` |
| `insufficient_data` | Drawdown with no usable facts | `insufficient_data` |

Price drawdown alone never sets `broken`.

## Portfolio loser feedback

Config defaults (`HypothesisIntegrityConfig`):

- Count tolerance: ≤ **40%** of holdings underwater
- NAV tolerance: ≤ **35%** of book NAV underwater

`balancing_hint` values:

| Hint | When |
|------|------|
| `tolerate_intact_losers` | Within band; losers are thesis-intact |
| `hold_intact_review_selection` | Outside band but losers still intact — check selection criteria |
| `trim_weakening_losers` | Outside band with weakening theses |
| `rotate_broken_first` | Any broken-thesis losers |
| `maintain` | No special pressure |

`selection_feedback_flags` highlight model families that fail more often among
losers than non-losers (feeds analysis-review / scoring experiments).

## Wiring (does not auto-sell)

| Layer | Effect |
|-------|--------|
| Surveillance | Stop-hit + intact thesis → **watch** (not action); underwater broken → action |
| `exit_urgency` | Intact dampens urgency and skips crude −10% bump; broken boosts urgency |
| Graduated harvest | Uses hypothesis-aware urgency |
| Analysis / Learning Director | Slim rollup in weekly payloads |

Automated / AI / graduated tracks already exit via target-set + confirm screens,
not hard stops. Technical-mode hard stops remain for the timing baseline track
(see deferred ideas).

## Human gate

Sunday: when any track is outside loser tolerance or has `broken_loser_count > 0`,
read the track’s `hypothesis_integrity.md` before promoting churn/scoring
experiments. Do **not** auto-apply stop replacements or knob changes from this
strand alone.

## Related

- [`exit-timing-cohorts.md`](exit-timing-cohorts.md) — hold-recovery probabilities
- [`loser-snapshot-cards.md`](loser-snapshot-cards.md) — avoid / failed-buy alumni forensics
- [`capital-allocation.md`](capital-allocation.md) — graduated entry/exit appetite
- Vision phase `hypothesis_first_exit` in `docs/data/learning_director_vision.json`
