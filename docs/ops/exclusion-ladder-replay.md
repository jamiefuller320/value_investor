# Exclusion ladder replay (rebalance_log + costs)

Phase 2 of the graduated loser-filter path: replay archive ladder priors on
paper `rebalance_log` passes **with trade costs**, then optionally spawn a
frozen exclusion shadow track for forward observation.

Complements [exclusion-universe-archive-sim.md](exclusion-universe-archive-sim.md)
(Phase 1 — universe EW, gross of costs).

## When to run

| Trigger | Command |
|---------|---------|
| **After exclusion archive** | `ftse-exclusion-universe-archive` then ladder replay |
| **Sunday analysis-review** | Wired in `analysis-review.yml` after archive step |
| **Before shadow spawn** | Confirm `readiness.ready_for_shadow_spawn` |

Requires acted `rebalance_log` entries on target tracks (≥2 for meaningful replay).

## Commands

```bash
# Replay default ladder on ai_judgment + rules
ftse-exclusion-ladder-replay run \
  --paper-root docs/data/paper_automation \
  --data-dir docs/data

# JSON output
ftse-exclusion-ladder-replay run --json

# Spawn frozen exclusion shadow from recommended step (u4 default)
ftse-exclusion-ladder-replay spawn-shadow \
  --paper-root docs/data/paper_automation \
  --data-dir docs/data

# Re-seed shadow fund from parent log replay
ftse-exclusion-ladder-replay warm-start --step-id u4 --force
```

## Artifacts

Written under `--paper-root`:

| File | Purpose |
|------|---------|
| `exclusion_ladder_replay.json` | Slim store |
| `exclusion_ladder_replay_review.json` | Per-track ladder replay + readiness |
| `ai_judgment_exclusion_u4/config.json` | Shadow track after spawn |
| `ai_judgment_exclusion_u4/exclusion_provenance.json` | Spawn + warm-start metadata |

`ftse-analysis-review` payload includes `exclusion_ladder_replay` when present.

## Readiness gate

`ready_for_shadow_spawn` is true when on **ai_judgment**:

1. Recommended ladder step replay has ≥2 acted log entries
2. `return_delta_vs_actual` > 0 on the monitoring window

Shadow tracks are **observe-only**:

- Knobs frozen (`is_exclusion_shadow: true`)
- `ftse-decision-review --apply` disabled (same as calibration shadows)
- Included in weekday `ftse-paper-auto --tracks all` when spawned

## Promotion workflow (human gate)

1. Phase 1: positive `cumulative_exclusion_alpha` in archive lab
2. Phase 2: positive `return_delta_vs_actual` on rebalance_log replay
3. Spawn shadow → forward marks vs parent `ai_judgment`
4. Only then consider `paper_knobs` on primary (manual — no auto-apply)

## Limitations

- Log replay covers logged passes only; pre-log history needs archive lab
- AI overlay replay uses logged `candidates` / `screen_buy_tier` (PIT at entry)
- Shadow warm-start seed P&L is diagnostic; judge forward epoch only

See also: [knob-calibration.md](knob-calibration.md), [decision-review.md](decision-review.md).
