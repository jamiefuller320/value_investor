# Capital allocation (graduated entry / exit)

Observe-only experimental strand for **dynamic capital recycling** as the book
widens beyond hero 3-position sleeves.

## What runs now (v1)

| Component | Status | Role |
|-----------|--------|------|
| `capital_allocation.py` | **Implemented** | Deterministic `entry_appetite`, `exit_urgency`, `swap_score`, lifecycle labels |
| `graduated_allocation` paper track | **Implemented** | Screen-rules book with trade-plan starter sizing + harvest skims |
| `run_graduated_rebalance()` | **Implemented** | Weekday paper-auto when `use_graduated_allocation=true` |
| Equal-weight primary / AI tracks | Unchanged | Control path stays equal-weight |

### Paper track

```bash
ftse-paper-auto --output-dir docs/data/paper_automation --tracks graduated_allocation --force
```

Directory: `docs/data/paper_automation/graduated_allocation/`

Defaults vs rules control:

- `max_positions`: **4** (wider book for sleeve mechanics)
- `skip_timing_wait`: true (same as rules — wait names excluded from *new* buys)
- Entry size: `trade_plan.core_allocation_pct` when present, else appetite-derived fraction
- Harvest: partial skim when `exit_urgency` ≥ threshold and unrealized gain ≥ 15%

Compare vs `rules`, `momentum_grace`, and `ai_judgment` in
`learning_tracks_review.json` after a few weeks of marks.

## Algorithm vs agent — division of labour

| Layer | Owner | Cadence | What it does |
|-------|-------|---------|--------------|
| **Scoring & rebalance** | Pure algorithm | Every weekday paper-auto | Rank targets, size entries, skim harvests, apply churn guards |
| **Knob steps** | `ftse-decision-review` (algorithm) | Weekly when history thick | Small steps on `max_positions`, conviction floor, etc. — **not** on graduated thresholds yet |
| **Experiment inventory** | Learning Director (agent) | Sunday | Recommend activate/hold/retire vision phases; flag complexity budget |
| **Roadmap activation** | Human + Director proposal | Weekly ops review | No auto-promote to primary or live capital |
| **Swap-score gating** | Algorithm (planned v2) | Rebalance pass | Only rotate when `swap_score` clears cost margin |
| **Conviction-weighted sleeves** | Algorithm (planned v3) | Shadow track | Replace equal-weight denominator across names |

**Learning Director remit:** Yes — include graduated allocation in weekly synthesis
(experiment inventory, convergence with loser-filter strand, vision phase
`graduated_allocation_track`). The Director should **not** own day-to-day sizing;
it proposes when to widen `max_positions`, promote shadows, or retire failed experiments.

**Separate sub-agent?** Not yet. A dedicated “allocation architect” agent would
duplicate the Director unless experiment count exceeds the complexity budget
(>5 open experiments or >4 frozen shadows). Revisit if weekly Director reviews
consistently under-weight capital-allocation evidence.

## Vision phases (learning_director_vision.json)

| Phase | Status | Activate when |
|-------|--------|---------------|
| `graduated_allocation_track` | **active** | v1 shadow running |
| `hypothesis_first_exit` | **active** | Underwater thesis cards + loser tolerance |
| `capital_rotation_coordinator` | planned | Exit-timing cohorts ready + swap rotations ≥10 closed |
| `conviction_weighted_sizing` | planned | Graduated track ≥8 epoch marks; cost_drag stable |

Deferred store: **L176** (conviction-weighted sizing), **L177** (full lifecycle
state machine), **N38** (no live capital promotion before paper evidence).

## Planned (not built)

1. **Swap-score gate** — sell→buy only when rotation beats hold after 2× round-trip cost
2. **Per-holding lifecycle state** in `rebalance_state` (prospect→starter→build→full→harvest→grace→exit)
3. **Conviction-weighted sleeves** — target = f(conviction) not NAV/N
4. **Cash buffer target** — maintain 5–10% NAV dry powder for new cycle entries
5. **AI-judgment graduated track** — same mechanics with research gates (after rules shadow proves value)

## Evidence pairing

| Artifact | Question |
|----------|----------|
| `rebalance_log.json` (graduated_allocation) | Do starter sizes reduce churn vs equal-weight? |
| `exit_timing_cohorts.json` | Do harvest skims improve swap-rotation outcomes? |
| `learning_tracks_churn_health.json` | Cost drag vs rules / momentum_grace |
| `knob_calibration` replay | Sensitivity of `max_positions` 4–5 |

## Safety

- Observe-only — no `decision-review --apply` on graduated thresholds yet
- Primary AI track unchanged
- Screen signals frozen (N3)
- Live capital off until stage 2b + graduated shadow beats control (N38)

See also [`primary-learning-track.md`](primary-learning-track.md),
[`learning-director-vision.md`](learning-director-vision.md),
[`exit-timing-cohorts.md`](exit-timing-cohorts.md),
[`hypothesis-integrity.md`](hypothesis-integrity.md).
