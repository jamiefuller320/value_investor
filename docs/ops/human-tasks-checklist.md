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
| **GHA secret hygiene** scan (skips if no merges / workflow touches in 36h) | CI | [gha-secret-hygiene.md](gha-secret-hygiene.md#automated-daily-check) |

## Sunday

| Task | Who | Doc |
|------|-----|-----|
| Read **analysis review** synthesis (`analysis_review.md`) plus the observe-only **chart-outcome** mix | Human | [analysis-review.md](analysis-review.md#artifacts) |
| Review **knob calibration priors** (`ranking_mode`, `ready_for_shadow_bootstrap`, `bootstrap_priors`) | Human | [knob-calibration.md](knob-calibration.md#promoting-a-prior-human-gate) |
| Review **unified experiment assessment** (`experiment_assessment.json`) — after the 2026-09-03 human pass, task recommends should be empty (u4/exit-shadow watch; scoring on engineering queue) | Human | [experiment-assessment.md](experiment-assessment.md#human-gate) |
| Compare **calibrated shadows vs primary** AI judgment on Automation tab | Human | [knob-calibration.md](knob-calibration.md#competing-calibrated-shadows) |
| **Promote knob priors** only when a survivor passes gates (do not edit `ai_judgment/config.json` early) | Human | [knob-calibration.md](knob-calibration.md#promoting-a-prior-human-gate) |
| **Fair-cost gate** — keep 3% books as churn lab; require `ftse-trading-costs assess` / fair shadows before calling excess deployable | Human | [market-trading-costs.md](market-trading-costs.md#test-and-adoption-strategy-dual-suite) |
| **Suite B fair-cost lab** — review `ai_judgment_fair` / `rules_fair` marks; keep `--suite B` applies suite-local; no primary flip until B clears gates | Human | [market-trading-costs.md](market-trading-costs.md#near-term-actions) |
| **Selective A→B fair twins** — if assessment has recommend calibration/exclusion/experimental rows, dry-run then optionally apply `ftse-trading-costs spawn-fair-twins` (max 2; never auto-fork) | Human | [market-trading-costs.md](market-trading-costs.md#selective-a-to-b-fair-cost-twins) |
| Review **entry DCA cadence** when `ready_for_cadence_analysis` fires | Human | [position-lifecycle.md](position-lifecycle.md#human-gate) |
| Review **hypothesis integrity** when losers breach tolerance or theses break | Human | [hypothesis-integrity.md](hypothesis-integrity.md#human-gate) |
| Triage **analysis_tasks** — persist/publish/apply `system_gaps` flags auto-queue as `eng-sgap-*` (no dispatch); promote remaining produce/clock flags by hand; scoring stays `eng-20260903-02` / `eng-20260903-03` (observe-only; no `assign_signal()` edits); do not revive cancelled knob counterfactuals | Human | [analysis-review.md](analysis-review.md#manual-promotion-to-engineering) |
| Check **exclusion ladder spawn gate** — if `ready_for_shadow_spawn`, run `ftse-exclusion-ladder-replay spawn-shadow` (never auto) | Human | [exclusion-ladder-replay.md](exclusion-ladder-replay.md#promotion-workflow-human-gate) |
| Triage **paper_learning_tasks** + **learning_director_tasks** — watch u4 + exit-shadow; leave L111 as continue; buffered-hold and IMB.L are done; no promote CLI | Human | [paper-learning-review.md](paper-learning-review.md#enacting-proposed-experiments) |
| Full-period knob calibrate + shadow bootstrap + PIT warm-start + endurance | CI | [knob-calibration.md](knob-calibration.md#warm-start-zero-datum-forward-only-endurance) |

### Promotion gate (AI judgment knobs)

Do **not** promote calibration priors to `ai_judgment/config.json` until:

1. A shadow has status **recommend** in `experiment_assessment.json` (or **surviving** in `calibration_shadow_endurance.json`)
2. `ready_for_priors: true` / `ready_for_shadow_bootstrap` look sound in `knob_calibration_priors.json`
3. `score_gap_vs_runner_up ≥ 0.005`
4. `recommended_prior.confidence` is acceptable (not `insufficient` / thin `low`)
5. **Fair-cost view** supports treating excess as deployable (`ftse-trading-costs assess` and/or fair-cost shadows) — 3% stress excess vs ^FTSE alone is not the adoption datum

Survivors are **starting priors for learning-loop refinement** — never auto-apply.

## Monthly

| Task | Who | Doc |
|------|-----|-----|
| Follow **unified ops review cadence** (weekly → monthly → quarterly) | Human | [ops-review-cadence.md](ops-review-cadence.md#sequence) |
| **Horizon scan** — weeder drops near-dups; triage remaining fragments | Human | [horizon-scan.md](horizon-scan.md#when-it-runs) |
| Review **euro_depth filing/memo parity** vs FTSE before AI-gate / Phase 3 | Human | [market-sharded-learning.md](market-sharded-learning.md#depth-first-eu-pilot-aug-2026) |
| Review **cycle-end Cursor surplus** — assess unused Ultra fraction, apply a 25% provisional weekly_ops bump (15% of plan credit / week is a warning on estimated USD, not a hard cap), keep or revert at the next cycle. Do not raise rememo daily caps or offline memo density from leftover credit | Human | [cycle-budget-surplus.md](cycle-budget-surplus.md#human-gate) |

## Quarterly

| Task | Who | Doc |
|------|-----|-----|
| **Deferred ideas** review (`ftse-defer status`) | Human | [deferred-review.md](../deferred-review.md) |

## Ad hoc (when triggered)

| Task | Who | Doc |
|------|-----|-----|
| **Decision packs** before live capital (verify checklist) | Human | [primary-learning-track.md](primary-learning-track.md#success-datums) |
| **Paper-learning review** when churn / exit-timing cohorts mature | Human | [paper-learning-review.md](paper-learning-review.md) |
| **Re-import library ingest crons** after cadence changes (Mon–Sat peak + daily off-peak; sprint ≤4×/day × 24; maintenance ≤4×/day × 62) | Human | [euro-depth-sprint.md](euro-depth-sprint.md#register-euro-ingest-crons-after-cadence-changes) |
| **Register ops-monitor 13:15 catch-up** on cron-job.org after email-deferral merge | Human | [ops-monitor.md](ops-monitor.md#email-deferral-day-complete-gate) |
| **Rotate `CURSOR_API_KEY`** (and review Actions) if Cursor API misuse or secret exposure is suspected | Human | [gha-secret-hygiene.md](gha-secret-hygiene.md#if-cursor_api_key-may-already-be-compromised) |
| **Register daily GHA secret-hygiene cron** on cron-job.org after merge (`import_cron_jobs.py --job gha-secret-hygiene`) | Human | [gha-secret-hygiene.md](gha-secret-hygiene.md#automated-daily-check) |
| **Sync valid Cursor key into GitHub Actions** (`CURSOR_API_KEY_V2` + `CURSOR_API_KEY`) when legacy secret is dead/missing | Human | [gha-secret-hygiene.md](gha-secret-hygiene.md#which-secret-workflows-use) |
| **Override FCF auto policy** only when majority/filing fallback is wrong (or so-what `fcf_bridge_needed` with no filing/company figure) | Human (residual) | [fcf-basis-bridges.md](fcf-basis-bridges.md#when-to-review-residual) |
| **Review ingest deviations** when Automation → Ingest deviations has open rows (IR exhausted / weekday cap + leftover IWB). Approve pins intensive; dismiss closes 7 days. Do not auto-replace IR URLs | Human | [ingest-deviations.md](ingest-deviations.md#what-needs-a-human) |

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
