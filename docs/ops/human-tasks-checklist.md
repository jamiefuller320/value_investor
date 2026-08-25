# Human tasks checklist

Manual gates for the **primary learning loop**, **knob calibration**, and
**promotion decisions**. Weekday paper-auto and Sunday analysis-review handle
most automation — this list is what still needs a human.

**Dashboard:** Automation tab → **Human tasks** (links below mirror this doc).

**Cadence map:** [`ops-review-cadence.md`](ops-review-cadence.md) — weekly analysis → monthly horizon → quarterly deferred.

**Canonical JSON:** [`docs/human_tasks_checklist.json`](../human_tasks_checklist.json)
— update this file **and** this markdown when adding tasks (see
[maintenance rule](#maintenance)).

## Weekday (Mon–Fri)

| Task | Who | Doc |
|------|-----|-----|
| **Spot-check learning tracks** after paper-auto — AI excess vs ^FTSE, rules control, competing calibrated shadows | Human | [primary-learning-track.md](primary-learning-track.md#commands) |
| Paper-auto + decision-review `--apply` (all tracks; shadows observe-only; endurance ledger) | CI | [decision-review.md](decision-review.md#commands) |

## Sunday

| Task | Who | Doc |
|------|-----|-----|
| Read **analysis review** synthesis (`analysis_review.md`) | Human | [analysis-review.md](analysis-review.md#artifacts) |
| Review **knob calibration priors** (`ranking_mode`, `ready_for_shadow_bootstrap`, `bootstrap_priors`) | Human | [knob-calibration.md](knob-calibration.md#promoting-a-prior-human-gate) |
| Review **unified experiment assessment** (`experiment_assessment.json`) | Human | [experiment-assessment.md](experiment-assessment.md#human-gate) |
| Compare **calibrated shadows vs primary** AI judgment on Automation tab | Human | [knob-calibration.md](knob-calibration.md#competing-calibrated-shadows) |
| **Promote knob priors** only when a survivor passes gates (do not edit `ai_judgment/config.json` early) | Human | [knob-calibration.md](knob-calibration.md#promoting-a-prior-human-gate) |
| Review **hypothesis integrity** when losers breach tolerance or theses break | Human | [hypothesis-integrity.md](hypothesis-integrity.md#human-gate) |
| Triage **analysis_tasks** — promote scoring/ingest via `ftse-analysis-review promote` | Human | [analysis-review.md](analysis-review.md#manual-promotion-to-engineering) |
| Check **exclusion ladder spawn gate** — if `ready_for_shadow_spawn`, run `ftse-exclusion-ladder-replay spawn-shadow` (never auto) | Human | [exclusion-ladder-replay.md](exclusion-ladder-replay.md#promotion-workflow-human-gate) |
| Triage **paper_learning_tasks** + **learning_director_tasks** — enact config probes or mark done; no promote CLI | Human | [paper-learning-review.md](paper-learning-review.md#enacting-proposed-experiments) |
| Full-period knob calibrate + shadow bootstrap + PIT warm-start + endurance | CI | [knob-calibration.md](knob-calibration.md#warm-start-zero-datum-forward-only-endurance) |

### Promotion gate (AI judgment knobs)

Do **not** promote calibration priors to `ai_judgment/config.json` until:

1. A shadow has status **recommend** in `experiment_assessment.json` (or **surviving** in `calibration_shadow_endurance.json`)
2. `ready_for_priors: true` / `ready_for_shadow_bootstrap` look sound in `knob_calibration_priors.json`
3. `score_gap_vs_runner_up ≥ 0.005`
4. `recommended_prior.confidence` is acceptable (not `insufficient` / thin `low`)

Survivors are **starting priors for learning-loop refinement** — never auto-apply.

## Monthly

| Task | Who | Doc |
|------|-----|-----|
| Follow **unified ops review cadence** (weekly → monthly → quarterly) | Human | [ops-review-cadence.md](ops-review-cadence.md#sequence) |
| **Horizon scan** + triage open `ftse-defer` fragments | Human | [horizon-scan.md](horizon-scan.md#when-it-runs) |
| Review **euro_depth filing/memo parity** vs FTSE before AI-gate / Phase 3 | Human | [market-sharded-learning.md](market-sharded-learning.md#depth-first-eu-pilot-aug-2026) |

## Quarterly

| Task | Who | Doc |
|------|-----|-----|
| **Deferred ideas** review (`ftse-defer status`) | Human | [deferred-review.md](../deferred-review.md) |

## Ad hoc (when triggered)

| Task | Who | Doc |
|------|-----|-----|
| **Decision packs** before live capital (verify checklist) | Human | [primary-learning-track.md](primary-learning-track.md#success-datums) |
| **Paper-learning review** when churn / exit-timing cohorts mature | Human | [paper-learning-review.md](paper-learning-review.md) |
| **Re-import euro ingest crons** after cadence changes (4×/day × 24 targets) | Human | [euro-depth-sprint.md](euro-depth-sprint.md#register-euro-ingest-crons-after-cadence-changes) |

## Maintenance

When you introduce a **new human task** (ops gate, promotion step, review cadence):

1. Add a row to the relevant section **here**.
2. Add a matching entry to [`docs/human_tasks_checklist.json`](../human_tasks_checklist.json)
   (`id`, `title`, `summary`, `doc_path`, optional `doc_anchor`, `automated`).
3. Run `pytest tests/test_human_tasks_checklist.py`.
4. Republish dashboard (`ftse-publish`) or wait for the next workflow so the UI picks up JSON changes.

Agents: follow `.cursor/rules/human-tasks-checklist.mdc`.

See also: [ops-review-cadence.md](ops-review-cadence.md),
[primary-learning-track.md](primary-learning-track.md),
[knob-calibration.md](knob-calibration.md).
