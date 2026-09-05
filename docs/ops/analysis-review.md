# Modelling & analysis review

Read-only agent synthesis over backtest, historical analysis, offline simulation,
paper learning-track artifacts, and **trajectory evidence** (PIT prediction
calibration). The review’s job is to turn that evidence into **focus areas that
refine assessment models** — proposed `[scoring]` / `[offline_sim]` experiments —
not to archive metrics for their own sake. **Does not** change live paper books,
apply decision-review knobs, or open engineering PRs automatically.

## When it runs

| Trigger | Schedule |
|---------|----------|
| **cron-job.org (primary)** | Sunday **10:35 UTC** (`35 10 * * 0`); optional backup `35 12 * * 0` |
| GitHub cron (backup) | Sunday 08:30 UTC |
| Manual | Actions → **FTSE Analysis Review** → Run workflow |

External dispatch (same `WORKFLOW_DISPATCH_PAT` as orchestrator / ingest):

```bash
WORKFLOW=analysis-review.yml WORKFLOW_DISPATCH_PAT=… ./scripts/dispatch_github_workflow.sh
```

Schedule after the Sunday email quiet bundle so `docs/data/` is fresh. Same-day skip: a second fire exits quickly if a successful run already happened today.

See [orchestrator-cron.md](orchestrator-cron.md) for the repo-wide scheduling policy.

For a mid-week dashboard refresh (Analysis tab + optional modelling review after
engineering merges), see [accelerated-review-cycle.md](accelerated-review-cycle.md).

## Prerequisites

At least one of:

- `docs/data/history/` with **≥2** weekly run snapshots (after history persistence), or
- `docs/data/paper_automation/learning_tracks_review.json` (paper marks available)

Sunday workflow first runs `ftse-archive-history` to densify `docs/data/history/` from
dashboard archives, then trajectory evidence and the wider exit-timing near-miss sim.

If history is still seeding, the workflow logs `payload` readiness and skips the agent.

## Artifacts

| File | Purpose |
|------|---------|
| `docs/data/experiment_assessment.json` | Unified experiment loop (continue / fail / recommend) |
| `docs/data/system_gaps.json` | Deterministic learning-path integrity snapshot (no LLM) |
| `docs/data/analysis_review.md` | Human-readable synthesis |
| `docs/data/analysis_review.json` | Structured sections + metadata |
| `docs/data/analysis_tasks.json` | Proposed experiments (`status: proposed`) |
| `docs/data/trajectory_evidence_review.json` | PIT transition outcomes + `model_focus_candidates` (payload input) |
| `docs/data/chart_outcome_review.json` | Buy-tier chart timing vs frozen initial levels (observe-only) |
| `docs/data/ingest_trials.json` | Ingest experiments with `review_trigger: analysis_review` or `both` |

## Trajectory evidence → scoring experiments

Sunday `analysis-review.yml` runs `ftse-trajectory-evidence` **before** the modelling
agent. The payload includes a slim `trajectory_evidence` object (hit rates, lag,
`model_focus_candidates`). When candidates exist, the agent must propose at least
one `[scoring]` or `[offline_sim]` experiment citing a candidate — human promote
still required (`ftse-analysis-review promote`). Frozen `assign_signal()` thresholds
stay off-limits (N3).

See [trajectory-evidence.md](trajectory-evidence.md).

## Chart outcomes (observe-only)

Sunday `analysis-review.yml` and `ftse-publish` refresh
[`chart-outcome-review.md`](chart-outcome-review.md) from `docs/data/charts/`.
The payload includes a slim `chart_outcome_review` (verdict, stop/target counts,
well-timed / weakest samples). **Cite it as timing context only** — do not
propose knob applies or scoring experiments from first-cross labels until that
loop is explicitly promoted. Frozen `assign_signal()` thresholds stay off-limits (N3).

The same Sunday job then runs `ftse-news-phrase-trajectory --mode rolling` (observe-only
buy∪boundary phrase lexicon) and `ftse-news-event-journal --mode rolling` (observe-only
material-event extract from the same headlines, joined to later filings). Soft-fail;
artifacts commit with the trajectory bootstrap bundle. See
[news-phrase-trajectory.md](news-phrase-trajectory.md) and
[news-event-journal.md](news-event-journal.md).

## Loser cards, exclusion, and exit-timing → filter experiments

The same Sunday payload includes slim:

| Key | Action contract |
|-----|-----------------|
| `loser_snapshot_cards` | ≥1 `[scoring]` / `[offline_sim]` when `top_failed_families` non-empty |
| `exclusion_universe` | ≥1 `[offline_sim]` / `[paper_knobs]` when `ready_for_priors` or positive exclusion alpha |
| `exclusion_ladder_replay` | ≥1 `[monitoring]` / `[paper_knobs]` spawn-shadow gate when `ready_for_shadow_spawn` (human CLI; never auto) |
| `exit_timing_cohorts` / `exit_timing_near_miss` | ≥1 `[paper_churn]` / `[offline_sim]` when probability readiness fires |
| `entry_dca_overlay` | ≥1 `[paper_churn]` / `[offline_sim]` when `ready_for_cadence_analysis` (cite leading cadence; do not execute DCA) |
| `system_gaps` | ≥1 `[ops]` / `[ingest]` / `[coverage]` / `[monitoring]` when `flags` is non-empty, citing the highest-severity flag id |

Cap five experiment lines; overflow goes to **DEFER**.

## System gaps (learning-path integrity)

Sunday `analysis-review.yml` writes [`docs/data/system_gaps.json`](../data/system_gaps.json)
**even when the modelling agent is skipped**. The snapshot is deterministic — it does
not mine conversation transcripts.

It exists because healthy ops counters can hide consumer-path misses:

| Counter that looks green | What it can hide |
|--------------------------|------------------|
| `weekly_ops` remaining / not constraining | Research skipped as already-done; rememo never runs |
| Ladder `executed: 0` + `already_researched` | Thin / zero-body first-pass memos counted as coverage |
| Memo file exists / 100% buy-tier files | Verdict never wired onto the report the paper book reads |
| Filing parity / maintenance ingest | Observe-sim / screen-lite clock stale; not `learning_ready` |
| Feature tests green | Overlay JSON in `output/` never persisted to `docs/data/` |

Layers in the snapshot: **produce → persist → publish → apply**, plus
**learning_clock** (filing-ready vs learning-ready). The analysis agent must answer
`probe_questions` in a **SYSTEM GAPS** section and must not treat unused budget or
file existence as proof the learning path is fed.

```bash
ftse-analysis-review system-gaps --json
ftse-analysis-review system-gaps --write
ftse-analysis-review compile-system-gaps --promote --json
```

Sunday `analysis-review.yml` compiles high flags into `analysis_tasks.json`
(`ana-sgap-<flag_id>`) even when the modelling agent is skipped.

**Auto-promote (narrow):** persist / publish / apply high flags
(`overlay_persist_hole`, `overlay_lagging_committed`, `research_index_shrunk`,
`buy_tier_unwired_verdict`) open `eng-sgap-<flag_id>` rows with title-dedupe.
That is the written≠wired class from the morning miss. Produce and
`learning_clock` flags stay **proposed** for human
`ftse-analysis-review promote`. Neither path dispatches engineering agents.

The overview dashboard card **Learning-path gaps** reads the snapshot (bundle
or `data/system_gaps.json` sidecar).

## Experiment assessment ledger

Sunday workflow runs `ftse-experiment-assess refresh` after knob endurance. The payload
includes slim `experiment_assessment` (`summary`, `recommendations`, `by_status`).
When `recommendations` is non-empty, include a `[monitoring]` line — human ack only;
never auto-apply. See [experiment-assessment.md](experiment-assessment.md).

## Ingest trials

Runs recorded with `--trial-review-trigger analysis_review` (or `both`) appear in the
weekly payload as `ingest_trials_pending_review`. The agent should reference them under
**PROPOSED EXPERIMENTS** (ingest area). Horizon-flagged trials (`horizon_scan`) are
reviewed in the monthly horizon scan instead.

## Manual promotion to engineering

Review experiments, then promote scoring/ingest candidates into the supervised queue:

```bash
ftse-analysis-review list
ftse-analysis-review promote --task-id ana-20260903-01
ftse-engineering list
```

Queued scoring candidates (promoted 2026-09-03):

- `eng-20260903-02` ← `ana-20260903-01` — hold→buy / `signal_unchanged` 1w hit-rate overlay
- `eng-20260903-03` ← `ana-20260903-02` — quality-family composite gate on the avoid cohort

Do not promote cancelled knob-retune probes (`ana-20260728-02` and the N58/N59 paper-learning cancels).

Only `scoring`, `ingest`, `prompt`, `coverage`, and `ops` areas promote to
`engineering_tasks.json`. `offline_sim` and `paper_knobs` experiments stay
analysis-only — run counterfactuals or decision-review probes manually.
`paper_churn` experiments from [`paper-learning-review.md`](paper-learning-review.md)
stay manual (config guard tuning).

## Guardrails

- No edits to `paper_fund`, `paper_automation`, `simulator`, or `paper-auto.yml`
- No `decision-review --apply` from this track
- No base `assign_signal()` changes (N3)
- LLM synthesis only; knob changes remain rule-based (N24)

See also: [`horizon-scan.md`](horizon-scan.md) (monthly strategic foresight + fragments).
