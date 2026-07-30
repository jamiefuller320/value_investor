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

# Apply clamped updates when ≥4 equity marks and ≥2 trades
ftse-decision-review --output-dir docs/data/paper_automation --tracks all --apply
```

Weekday `paper-auto.yml` seeds prior state, refreshes research overlay on
`docs/data/latest.json`, runs all three tracks, then
`ftse-decision-review --tracks all --apply`. Thin history stays propose-only.

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

Post-exit shadow cohorts (`exit_shadow.json`, `exit_shadow_review.json`) score
1/4/8/12-week paths after full sells. Observe-only for now — grace knob
auto-tune is deferred until closed cohorts thicken (see `learning_tracks_exit_shadow.json`).

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
