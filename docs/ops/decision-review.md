# Decision-review learning (paper-auto)

Stage 1 loop: review the automated paper book **after costs**, then nudge small trading knobs. Screen signals stay frozen.

## Knobs

| Knob | Default | Role |
|------|---------|------|
| `max_positions` | 5 | Hard sleeve cap (bounds 3–8) |
| `skip_timing_wait` | true | Drop `timing_signal=wait` from new buys |
| `min_conviction` | 0.0 | Conviction floor (bounds 0–0.6) |
| `sector_cap` | 0.30 | Max equal-weight sleeves per *known* sector |

Stored in `docs/data/paper_automation/config.json` (and runtime `output/paper_automation/`).

## Commands

```bash
# Propose only (writes decision_review.json)
ftse-decision-review --output-dir docs/data/paper_automation

# Apply clamped updates when ≥4 equity marks and ≥2 trades
ftse-decision-review --output-dir docs/data/paper_automation --apply
```

Weekday `paper-auto.yml` seeds prior state, runs automation, then `ftse-decision-review --apply`. Thin history stays propose-only until marks accumulate.

## Artifacts

- `decision_review.json` — latest metrics, proposed changes, reasons
- `decision_review_history.json` — last 52 reviews

## Safety

- Steps are small (±1 position, ±0.05 conviction/sector).
- No screen-signal or model-weight edits (those stay in archive weight learning).
- Evolutionary genomes (L2) wait until this loop has thicker history.
