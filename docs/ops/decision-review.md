## Decision-review learning (paper-auto)

Primary loop: an **AI-judgment** paper book makes stock picks from research available
at decision time; confirmation is **excess return after costs vs the market**
(^FTSE), with a **rules** book as control. See
[`primary-learning-track.md`](primary-learning-track.md).

Screen signals stay frozen (N3). Knobs nudge slowly when history is thick.

## Knobs

| Knob | Default | Role |
|------|---------|------|
| `max_positions` | 5 | Hard sleeve cap (bounds 3–8) |
| `skip_timing_wait` | true | Drop `timing_signal=wait` from new buys |
| `min_conviction` | 0.0 | Conviction floor (bounds 0–0.6) |
| `sector_cap` | 0.30 | Max equal-weight sleeves per *known* sector |
| `use_adjusted_signal` | false / **true on AI track** | Gate on research overlay signal |
| `require_research_accumulate` | false / **true on AI track** | Only buy when memo verdict is accumulate |

Stored per track in `docs/data/paper_automation[/ai_judgment]/config.json`.

## Commands

```bash
# Run both tracks
ftse-paper-auto --output-dir docs/data/paper_automation --tracks all

# Review both vs market (writes learning_tracks_review.json)
ftse-decision-review --output-dir docs/data/paper_automation --tracks all

# Apply clamped updates when ≥4 equity marks and ≥2 trades
ftse-decision-review --output-dir docs/data/paper_automation --tracks all --apply
```

Weekday `paper-auto.yml` seeds prior state, runs both tracks, then
`ftse-decision-review --tracks all --apply`. Thin history stays propose-only.

## Artifacts

- `learning_tracks_summary.json` / `learning_tracks_review.json` — dual-track rollup
- `decision_review.json` — per-track metrics, proposed changes, reasons
- `decision_review_history.json` — last 52 reviews per track

## Safety

- Steps are small (±1 position, ±0.05 conviction/sector).
- No screen-signal or model-weight edits (those stay in archive weight learning).
- Evolutionary genomes (L2) wait until this loop has thicker history.
- Do not promote AI gates to live capital until the primary track shows persistent
  excess vs market and vs the rules control.
