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
| **Spot-check learning tracks** after paper-auto — AI excess vs ^FTSE, rules control, calibrated shadow knobs | Human | [primary-learning-track.md](primary-learning-track.md#commands) |
| Paper-auto + decision-review `--apply` (all tracks; shadow observe-only) | CI | [decision-review.md](decision-review.md#commands) |

## Sunday

| Task | Who | Doc |
|------|-----|-----|
| Read **analysis review** synthesis (`analysis_review.md`) | Human | [analysis-review.md](analysis-review.md#artifacts) |
| Review **knob calibration priors** (`ready_for_priors`, confidence, score gap, cohort axes) | Human | [knob-calibration.md](knob-calibration.md#promoting-a-prior-human-gate) |
| Compare **calibrated shadow vs primary** AI judgment on Automation tab | Human | [knob-calibration.md](knob-calibration.md#calibrated-shadow-track-phase-1--ai_judgment-only) |
| **Promote knob priors** only when gates pass (do not edit `ai_judgment/config.json` early) | Human | [knob-calibration.md](knob-calibration.md#promoting-a-prior-human-gate) |
| Triage **analysis_tasks** — promote scoring/ingest via `ftse-analysis-review promote` | Human | [analysis-review.md](analysis-review.md#manual-promotion-to-engineering) |
| Knob calibrate + analysis-review agent (cohort fitness, spawn shadow) | CI | [knob-calibration.md](knob-calibration.md#when-to-run) |

### Promotion gate (AI judgment knobs)

Do **not** promote calibration priors to `ai_judgment/config.json` until:

1. `ready_for_priors: true` in `knob_calibration_priors.json`
2. `score_gap_vs_runner_up ≥ 0.005`
3. `recommended_prior.confidence` is acceptable (not `insufficient` / thin `low`)
4. Calibrated **shadow** forward marks support the change vs primary

## Monthly

| Task | Who | Doc |
|------|-----|-----|
| Follow **unified ops review cadence** (weekly → monthly → quarterly) | Human | [ops-review-cadence.md](ops-review-cadence.md#sequence) |
| **Horizon scan** + triage open `ftse-defer` fragments | Human | [horizon-scan.md](horizon-scan.md#when-it-runs) |

## Quarterly

| Task | Who | Doc |
|------|-----|-----|
| **Deferred ideas** review (`ftse-defer status`) | Human | [deferred-review.md](../deferred-review.md) |

## Ad hoc (when triggered)

| Task | Who | Doc |
|------|-----|-----|
| **Decision packs** before live capital (verify checklist) | Human | [primary-learning-track.md](primary-learning-track.md#success-datums) |
| **Paper-learning review** when churn / exit-timing cohorts mature | Human | [paper-learning-review.md](paper-learning-review.md) |

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
