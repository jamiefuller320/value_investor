# Progress report

Deterministic rollup of north-star progress, actionable deferred items, and
join-up checks. No LLM synthesis — it aggregates existing JSON builders and
read-only ops/engineering checks.

## When to run

| Cadence | Command | Purpose |
|---------|---------|---------|
| **Sunday** | After `ftse-publish` / quiet bundle | Refresh dashboard-facing progress snapshot |
| **Monthly** | With horizon scan prep | See deferred fragments + proposed tasks in one view |
| **Quarterly** | With deferred triage | Prioritise `defer_now` and `not_now` revisit triggers |
| **Ad hoc** | Before major promotion decisions | Confirm built components are joined up |

Daily integration health remains **`ftse-ops-monitor`** — this report adds
stage appraisal, deferred action lists, and role-coherence checks on top.

## Commands

```bash
# So-what gap closure (classify / dry-run / queue)
ftse-progress-report so-what
ftse-progress-report so-what --dry-run
ftse-progress-report so-what --apply

# Build and print markdown to stdout
ftse-progress-report build

# JSON to stdout (CI / scripting)
ftse-progress-report build --json

# Write committed artifacts
ftse-progress-report build --write

# Render markdown from saved JSON
ftse-progress-report markdown

# Local dashboard with Generate button API
ftse-dashboard-serve
# open http://127.0.0.1:8765/ → Overview → Generate fresh report
```

## Dashboard UI

Overview leads with the progress report card so review work is visible before screen context. The card includes a **So what? — needs your judgment** block for `human_gate` items (with runbook links). Auto-queued enforcement gaps are shown as counts only — they do not need a human prompt. Signal mix / trusts / WoW sit under a collapsed **Screen context** section.

Overview shows the latest `progress_report.json` with counts, actionable deferred
items, and integration / role-coherence warnings.

| Control | Behaviour |
|---------|-----------|
| **Generate fresh report** | Local: `POST /api/progress-report` via `ftse-dashboard-serve`. On GitHub Pages: dispatches the `progress-report` Actions workflow (requires a fine-grained PAT with Actions: Write stored in this browser via **Pages token**), then waits for Pages to publish the new JSON |
| **Reload** | Re-fetches published `data/progress_report.json` (cache-busted; same as a full page load) |
| **View full report** | Opens `data/progress_report.md` in the memo dialog |
| **Pages token** | Save / clear the browser-local PAT used for Pages generate (never committed) |

### GitHub Pages generate

Pages is static and cannot run `ftse-progress-report`. The Generate button:

1. Tries the local API (`ftse-dashboard-serve`).
2. If that is unavailable (404/405/network), dispatches
   [`.github/workflows/progress-report.yml`](../../.github/workflows/progress-report.yml)
   via the GitHub API.
3. Polls the workflow, then reloads `data/progress_report.json` after Pages deploy.

Initial Overview load also cache-busts `data/progress_report.json` (`?ts=…` +
`cache: "no-store"`). GitHub Pages serves JSON with `max-age≈600`, so a plain
refresh without busting can keep showing the previous report for up to ~10 minutes.

You can also run the workflow from the Actions UI (no PAT in the browser), or:

```bash
gh workflow run progress-report.yml -f force=true
# or
curl -X POST -H "Authorization: Bearer $WORKFLOW_DISPATCH_PAT" \
  -H "Accept: application/vnd.github+json" \
  https://api.github.com/repos/jamiefuller320/value_investor/dispatches \
  -d '{"event_type":"progress-report"}'
```

**PAT scope:** fine-grained token limited to this repo with **Actions: Write**.
That permission can dispatch *any* workflow in the repo — do not paste a broad
classic PAT, and clear the token on shared browsers (Overview → Pages token → Clear).

The workflow rebuilds `progress_report.json` / `.md`, syncs `project_progress.json`,
commits with `[skip ci]`, then explicitly dispatches `pages.yml` so the site refreshes.

## Artifacts

| File | Role |
|------|------|
| `docs/data/progress_report.json` | Machine-readable full report |
| `docs/data/progress_report.md` | Human-readable summary |

## Report sections

### 1. Overall progress

Reuses `build_project_progress()`:

- North-star stage statuses (0 → 5)
- Evidence (screen age, AI vs rules excess, library graduation, ops overall)
- Strengths, gaps, suggested next actions
- Ingest bottleneck block

### 2. Actionable now

| Bucket | Source | Action |
|--------|--------|--------|
| `defer_now` | `docs/deferred-ideas.json` | Promote to engineering / drop / done via `ftse-defer status` |
| `defer_not_now` | same | Review `revisit_when` triggers |
| Open fragments | same | Monthly horizon scan triage |
| Proposed review tasks | `analysis_tasks.json`, `horizon_tasks.json`, `learning_director_tasks.json` | Human promote or drop |
| Open engineering | `engineering_tasks.json` | Dispatch / review via engineering queue |

### 3. Integration health

Read-only slices of ops monitor checks (no auto-fixes):

- Committed JSON validity
- Ingest health log / stall detection
- Dashboard bundle freshness
- Engineering queue orphans, sync, compile drop risk
- Ops status snapshot age and consistency with project progress

### 4. So what? (gap closure)

Classifies live findings into `auto_queue` / `human_gate` / `observe`.
No-judgment enforcement gaps (e.g. FCF mismatch with uncapped buy-tier)
are queued by ops-monitor or `ftse-progress-report so-what --apply`.
See [so-what-gap-closure.md](so-what-gap-closure.md).

### 5. Role coherence (join-up)

Doctrine and wiring checks:

- Stage 2b focus vs negative AI learning edge
- Library breadth vs live expansion gate
- `defer_now` items without matching queue work
- Stale proposed review tasks (>14 days)
- Analysis / horizon artifacts vs proposed task queues
- Engineering tasks missing `allowed_paths`

Exit code is **1** when overall status is `fail` (same pattern as ops monitor).

## Related docs

- [ops-review-cadence.md](ops-review-cadence.md) — weekly / monthly / quarterly human loops
- [deferred-review.md](../deferred-review.md) — generated deferred ideas page
- [ops-monitor.md](ops-monitor.md) — daily automated health
- [so-what-gap-closure.md](so-what-gap-closure.md) — periodic so-what + auto gap-close
- [human-tasks-checklist.md](human-tasks-checklist.md) — manual gates

## Checklist registration

This report is **automated** (CLI only). Human gates it supports are already
registered under Sunday / monthly / quarterly sections in
[`docs/human_tasks_checklist.json`](../human_tasks_checklist.json).
