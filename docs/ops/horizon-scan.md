# Horizon scan (monthly strategic foresight)

Read-only agent synthesis over **stage gates**, **deferred ideas**, **scratch fragments**,
learning/evidence readiness, and the engineering queue. Complements weekly
[`analysis-review.md`](analysis-review.md) (backward metrics) with forward strategic
reconciliation.

Does **not** change paper books, apply knobs, or mine conversation transcripts.

## Scratch fragments

Capture half-formed thoughts before they are ready for a full defer entry:

```bash
ftse-defer fragment --text "exit timing vs counterfactual replay still fuzzy" \
  --tags exit_timing,counterfactual --source "session note"
ftse-defer list --fragments
ftse-defer fragment-status frag-20260811-01 done   # promoted/resolved
```

Fragments appear in [`deferred-review.md`](deferred-review.md) under **Open fragments**.
Horizon scan clusters them and may suggest `DROP` / `PROMOTE` actions (manual by default).

## When it runs

| Trigger | Schedule |
|---------|----------|
| GitHub cron | First **Sunday** of month **11:00 UTC** |
| Manual | Actions → **FTSE Horizon Scan** → Run workflow |

Run after weekly `analysis-review` when possible.

## Artifacts

| File | Purpose |
|------|---------|
| `docs/data/horizon_scan.md` | Human-readable synthesis |
| `docs/data/horizon_scan.json` | Structured sections |
| `docs/data/horizon_tasks.json` | ACCELERATE experiments (`status: proposed`) |
| `docs/data/ingest_trials.json` | Completed ingest experiments awaiting review (`--record-trial` on ingest-loop) |

## Ingest trials

Bounded ingest experiments (e.g. single-ticker depth) can be flagged for review:

```bash
ftse-ingest-loop run --max-targets 1 --record-trial \
  --trial-title "Single-ticker depth trial" \
  --trial-summary "…" \
  --trial-review-trigger horizon_scan
```

Workflow input `record_trial=true` does the same. Outcomes land in `ingest_trials.json`;
the monthly horizon scan payload includes `ingest_trials_pending_review` and an
**INGEST TRIALS REVIEW** section in the agent prompt.

## Commands

```bash
# Inspect inputs
ftse-horizon-scan payload --json

# Run agent (requires CURSOR_API_KEY)
ftse-horizon-scan run

# Manual apply after reviewing markdown
ftse-horizon-scan apply-defer --dry-run
ftse-horizon-scan apply-defer

ftse-horizon-scan apply-fragments --dry-run
ftse-horizon-scan apply-fragments

ftse-horizon-scan list

# Promote code-backed ACCELERATE into engineering queue (local; CI dispatches engineering-queue):
ftse-horizon-scan promote-engineering --all-engineering
# or: ftse-horizon-scan promote-engineering hor-20260811-01 hor-20260811-04
```

`promote-engineering` refreshes the dashboard queue snapshot (`automation.json` /
`latest.json`). Workflow input `promote_engineering=true` promotes after the agent run
and dispatches `engineering-queue.yml` when new tasks land. Skips `paper_knobs`
(manual process). Appends `eng-*` tasks with scoped `allowed_paths` and marks horizon
tasks `promoted`.

`apply-defer` and `apply-fragments` update `docs/deferred-ideas.json` and refresh
`deferred-review.md`. Workflow auto-apply is **off** by default — use dispatch inputs
`apply_defer` / `apply_fragments` only after reviewing the markdown.

## Guardrails

- Observe-only — same family as analysis review
- No conversation transcript mining (use fragments + defer)
- PARK proposals dedupe by title like `ftse-defer add`
- PROMOTE fragment → optional new deferred idea with `source=horizon_scan:promote:…`

## Related

- [`deferred-review.md`](deferred-review.md) — quarterly review of L/N items + fragments
- [`primary-learning-track.md`](primary-learning-track.md) — stage 2b focus
- [`PROJECT_OBJECTIVE.md`](PROJECT_OBJECTIVE.md) — north-star stages
- Deferred **L119** (this module)
