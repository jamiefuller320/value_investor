# Learning Director — vision & roadmap

Read-only **orchestration layer** above weekly analysis-review, paper-learning-review,
and monthly horizon-scan. Coordinates winner-pick vs loser-filter evidence, watches
regime drift, manages experiment complexity, and recommends **when** to activate
planned capabilities from the roadmap.

Does **not** apply knobs, mutate screens, spawn tracks, or open engineering PRs.

Structured roadmap for agents: [`docs/data/learning_director_vision.json`](../data/learning_director_vision.json).

## North star

Converge **top picking** and **bottom filtering** into a bettable model:

```
wide screen → progressive loser filters → filtered cohort → sleeve allocation → deployable book
```

Success is measured on the **filtered cohort** first (mostly-decent names), not on a
3-position hero portfolio alone. History length is fixed; **monitoring horizon** extends
via regular re-analysis and regime checks.

## Prediction philosophy

The aim remains to **predict future growth in value** of individual stocks. Useful
patterns are **changes in trajectory** — signals that it is time to **change opinion**
on a particular name (upgrade, downgrade, exclude, re-enter) — not a perfect
retrospective account of why a stock behaved as it did.

| Seek | Avoid |
|------|-------|
| Opinion-flip timing (conviction trend, timing overlay shifts) | Static level-fit on history |
| Forward cohort quality drift | In-sample narrative backstory |
| Early exclusion before damage compounds | Explaining every past loser in hindsight |

Structured in JSON as `prediction_philosophy` in
[`learning_director_vision.json`](../data/learning_director_vision.json).

## Weekly director (active — v1)

| Output section | Purpose |
|----------------|---------|
| **REGIME & ASSUMPTION CHECK** | Does evidence still hold as windows extend? Decay / reversal flags |
| **CONVERGENCE** | Reconcile winner-pick vs loser-filter strands |
| **COMPLEXITY & EXPERIMENT INVENTORY** | Open experiments, shadow tracks, budget |
| **VISION ROADMAP REVIEW** | Read `learning_director_vision.json`; recommend **activate / defer / retire** phases |
| **PROPOSED ACTIONS** | Numbered experiments and ops steps (human gate) |
| **HORIZON FRAGMENTS** | Up to 2 blue-sky observations → `ftse-defer fragment` (not tasks) |
| **DEFER** | Park until revisit triggers met |

The director **should** read the vision and recommend when to add roadmap elements —
using each phase's `revisit_when` and current payload evidence. It must not self-authorise
builds; it proposes activation with explicit triggers cited from JSON.

## Planned capabilities (not built yet)

| Phase | What | Activate when |
|-------|------|----------------|
| `regime_slices_8_16_24` | Rolling 8/16/24-week metric slices | ≥16 archive weeks |
| `filtered_cohort_track` | 15–20 EW sleeve cohort after ladder filter | u4 stable + replay gate |
| `loser_pattern_lab` | PIT loser feature attribution | Cohort track or ≥20 history runs |
| `filter_invention_loop` | Search invented exclusion rules | ≥3 validated patterns |
| `dual_objective_calibration` | Exclude + catch blended ranking | Cohort track ≥8 epoch marks |

## Complexity budget (default)

- ≤5 parallel open experiments across `analysis_tasks`, `paper_learning_tasks`, `learning_director_tasks`
- ≤4 frozen shadow tracks (calibration + exclusion + experimental)
- Director recommends **merge / retire / defer** when over budget

## Guardrails

- Observe-only — no `decision-review --apply`, no N3 screen writes
- Engineering promote remains manual (`ftse-analysis-review promote`, etc.)
- Vision activation recommendations are **proposals** — human ack in ops review

See [learning-director.md](learning-director.md) for commands and workflow.

## Agent roles (who challenges direction?)

| Agent | Cadence | Role |
|-------|---------|------|
| **Learning Director** | Weekly | Tactical orchestration + capped blue-sky **fragments** |
| **Horizon scan** | Monthly | Stage gates, evidence gaps, fragment clustering, PARK new defer ideas |
| **Quarterly defer review** | Quarterly | Promote/drop parked ideas |

Horizon scan is the **strategic challenger** today: it reads stage readiness, open
fragments, and deferred ideas, and may PARK new assumptions to challenge. It does not
yet have a dedicated section to attack `learning_director_vision.json` north-star
assumptions weekly — that gap is partly filled by director **HORIZON FRAGMENTS** (capture)
and horizon **FRAGMENT CLUSTERING / PARK** (synthesis). A separate devil's-advocate
agent is unnecessary unless monthly horizon proves insufficient after 2–3 cycles.
