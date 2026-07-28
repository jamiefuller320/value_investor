# Modelling & analysis review

Read-only agent synthesis over backtest, historical analysis, offline simulation,
and paper learning-track artifacts. **Does not** change live paper books, apply
decision-review knobs, or open engineering PRs automatically.

## When it runs

| Trigger | Schedule |
|---------|----------|
| GitHub cron | Sunday 08:30 UTC (catch-up after email quiet bundle) |
| Manual | Actions → **FTSE Analysis Review** → Run workflow |

Same-day skip: a second fire exits quickly if a successful run already happened today.

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

## Guardrails

- No edits to `paper_fund`, `paper_automation`, `simulator`, or `paper-auto.yml`
- No `decision-review --apply` from this track
- No base `assign_signal()` changes (N3)
- LLM synthesis only; knob changes remain rule-based (N24)

See also: [`primary-learning-track.md`](primary-learning-track.md), deferred L87.
