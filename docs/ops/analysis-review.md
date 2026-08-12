# Modelling & analysis review

Read-only agent synthesis over backtest, historical analysis, offline simulation,
and paper learning-track artifacts. **Does not** change live paper books, apply
decision-review knobs, or open engineering PRs automatically.

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

If history is still seeding, the workflow logs `payload` readiness and skips the agent.

## Artifacts

| File | Purpose |
|------|---------|
| `docs/data/analysis_review.md` | Human-readable synthesis |
| `docs/data/analysis_review.json` | Structured sections + metadata |
| `docs/data/analysis_tasks.json` | Proposed experiments (`status: proposed`) |
| `docs/data/ingest_trials.json` | Ingest experiments with `review_trigger: analysis_review` or `both` |

## Ingest trials

Runs recorded with `--trial-review-trigger analysis_review` (or `both`) appear in the
weekly payload as `ingest_trials_pending_review`. The agent should reference them under
**PROPOSED EXPERIMENTS** (ingest area). Horizon-flagged trials (`horizon_scan`) are
reviewed in the monthly horizon scan instead.

## Manual promotion to engineering

Review experiments, then promote scoring/ingest candidates into the supervised queue:

```bash
ftse-analysis-review list
ftse-analysis-review promote --task-id ana-20260728-02
ftse-engineering list
```

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
