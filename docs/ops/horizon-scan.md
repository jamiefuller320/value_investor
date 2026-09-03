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

Cadence context: [ops-review-cadence.md](ops-review-cadence.md) (weekly → monthly → quarterly).

## Artifacts

| File | Purpose |
|------|---------|
| `docs/data/horizon_scan.md` | Human-readable synthesis |
| `docs/data/horizon_scan.json` | Structured sections |
| `docs/data/horizon_tasks.json` | ACCELERATE experiments (`status: proposed`) |
| `docs/data/ingest_gap_closure_runs.json` | Completed ingest gap-closure runs awaiting review (`--record-gap-closure` on ingest-loop) |
| `docs/data/ingest_trials.json` | Legacy alias path (migrated into ingest_gap_closure_runs.json) |

## Ingest gap-closure runs

Bounded intensive gap-closure passes (e.g. single-ticker depth) can be flagged for horizon review:

```bash
ftse-ingest-loop run --max-targets 1 --record-gap-closure \
  --gap-closure-title "Single-ticker gap-closure pass" \
  --gap-closure-summary "…" \
  --gap-closure-review-trigger horizon_scan
```

Workflow input `record_gap_closure=true` does the same (`record_trial` is a deprecated alias).
Runs require outstanding ingest gaps (indexed_without_body or period bucket gaps). When a gap-closure
run fails refetch (`0/N` bodies), ingest-loop auto-compiles a scoped engineering task and dispatches
**engineering-queue**; after the engineering PR merges, engineering-queue chains a verification
**ingest-loop** rerun pinned to the same ticker. If gaps remain after verification, another
engineering round is compiled automatically (up to **3 rounds per chain**); the root run is marked
`chain_status: exhausted` when the cap is hit.

Non–gap-closure engineering merges use a sibling gate (`ftse-engineering verify-merged`):
scoped acceptance pytest on `main`, then a capped rework task if tests fail — see
[engineering-sync.md](engineering-sync.md#post-merge-acceptance-verify--capped-rework-l161).

**Automation (post-trial success):**
- **Weekly follow-up:** after a weekday batch ingest, ingest-loop dispatches `max_targets=1`
  gap-closure when buy-tier gaps persist (`trigger: weekly_followup`).
- **Library stall / slowdown:** after a complete `euro-ingest-loop` batch that is stalled
  or improved nobody with leftover buy-tier gaps, dispatch a pinned intensive pass
  (`trigger: stall_slowdown`). Partial / cutoff runs do not escalate.
- **Eng-idle hook:** when engineering-queue is idle (`open_count=0`) and paper holdings or top
  buy-tier names still have gaps, engineering-queue dispatches intensive gap closure
  (`trigger: eng_idle`).

Outcomes land in `ingest_gap_closure_runs.json`; the monthly horizon scan payload includes
`ingest_gap_closure_pending_review` (alias `ingest_trials_pending_review`) and an
**INGEST GAP CLOSURE REVIEW** section in the agent prompt.

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
