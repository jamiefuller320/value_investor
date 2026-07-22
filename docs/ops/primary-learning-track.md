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
| **Screen rules** *(control)* | `docs/data/paper_automation/` | Raw buy-tier screen signal | Baseline datum |

Both books use the same costs, position caps, and weekday paper-auto schedule.

## Success datums

1. **Market:** excess return after costs vs FTSE 100 (`^FTSE`) on the primary book.
2. **Control:** primary excess should also beat the rules book on the same window
   before promoting further knobs/gates.

Human verify-before-trade packs remain useful for live capital, but they are
**not** the primary learning loop.

## Commands

```bash
# Run both tracks after open settle
ftse-paper-auto --output-dir docs/data/paper_automation --reports docs/data/latest.json --tracks all

# Review both vs market; apply knobs only when history is thick
ftse-decision-review --output-dir docs/data/paper_automation --tracks all --apply
```

Artifacts: `learning_tracks_summary.json`, `learning_tracks_review.json`, plus
per-track `automated_fund.json` / `decision_review.json`.

## Safety

- Does **not** rewrite base screen `assign_signal()` (N3).
- Knob updates stay small and clamped (L1).
- Evolutionary genomes (L2) wait until this loop has thick walk-forward history.
- Live broker automation stays off until the primary track shows persistent excess.
