# Scheduling policy — external cron + GitHub Actions

GitHub `schedule` triggers are **best-effort** and have dropped Sunday/weekday runs in
this repo. **Production schedules should use cron-job.org** (or equivalent) calling
`workflow_dispatch` via a PAT. Keep in-repo `schedule:` blocks only as optional
backups when the workflow has **same-day skip** (safe to double-fire).

Human-readable inventory also appears on the dashboard automation page
(`ftse-publish` → `automation.json`).

## Policy (default for new workflows)

| Question | Answer |
|----------|--------|
| Must this run on a calendar? | Add a **cron-job.org** HTTP job → `workflow_dispatch` |
| GitHub `schedule:` in YAML? | Optional backup only; document external cron as primary |
| Same workflow fired twice same day? | Add same-day skip (or orchestrator child skip) before relying on backup cron |
| Bundled jobs (Sunday screen + ladder)? | Prefer **one** orchestrator dispatch, not many crons |
| PR merge / push triggers? | No external cron needed |
| Low-stakes hourly polling? | GitHub schedule may suffice; add external cron if misses matter |

**PAT:** fine-grained, **Actions: Read and write** on this repo only. Store as `GH_PAT`
on the cron host — never commit it.

**Helper scripts:**

- `scripts/dispatch_orchestrator.sh` — Sunday / weekday paper / surplus suites
- `scripts/dispatch_github_workflow.sh` — any single workflow file

## Coverage matrix

| Workflow | Production trigger | External cron (cron-job.org) | GitHub `schedule` backup |
|----------|-------------------|------------------------------|---------------------------|
| `automation-orchestrator.yml` | External **primary** | Sun 06:20 `SUITE=sunday`; Mon–Fri 08:20 `SUITE=weekday_paper` | Sun 06/09/12, daily 05:30, weekdays 08/11 |
| `email-report.yml` | Via orchestrator | ↑ (orchestrator dispatches) | None (by design) |
| `library-grow.yml` | Via orchestrator | ↑ | None |
| `library-model-review.yml` | Via orchestrator | ↑ | None |
| `paper-auto.yml` | Via orchestrator weekdays | ↑ | None |
| `ingest-loop.yml` | External **primary** | `5 7,10 * * 1,3,5` → `ingest-loop.yml` | Mon/Wed/Fri 07:00 + 10:00 |
| `analysis-review.yml` | External **primary** | `35 10 * * 0` (± optional `35 12 * * 0`) → `analysis-review.yml` | Sun 08:30 |
| `ops-monitor.yml` | External **primary** | `45 7 * * *` → `ops-monitor.yml` | Daily 07:45 |
| `data-backup.yml` | External **primary** | `30 12 * * 0` → `data-backup.yml` | Sun 12:30 (after email) |
| `engineering-queue.yml` | GitHub only today | Optional later if hourly misses hurt | Hourly weekdays |
| `engineering-agent.yml` | Queue / manual | No | No |
| `ci.yml` / `pages.yml` | Push / PR | No | No |

## One-time external cron setup

### 1. Orchestrator — Sunday quiet bundle (06:20 UTC)

```bash
export GH_PAT=…
SUITE=sunday ./scripts/dispatch_orchestrator.sh
```

Optional Sunday catch-up: repeat at **09:20 UTC** (`SUITE=sunday` or `SUITE=catchup_today`).

### 2. Orchestrator — weekday paper (08:20 UTC Mon–Fri)

```bash
GH_PAT=… SUITE=weekday_paper ./scripts/dispatch_orchestrator.sh
```

### 3. Ingest loop — Mon/Wed/Fri primary + catch-up (one job)

Schedule: `5 7,10 * * 1,3,5`

```bash
WORKFLOW=ingest-loop.yml GH_PAT=… ./scripts/dispatch_github_workflow.sh
```

Same-day skip in the workflow — safe alongside GitHub `0 7` / `0 10` schedules.

### 4. Analysis review — Sunday after email bundle (~10:35 UTC)

Run **after** the Sunday screen commits `docs/data/` (email via orchestrator often
finishes 08:00–11:00 UTC). Schedule: `35 10 * * 0` (optional backup `35 12 * * 0`).

```bash
WORKFLOW=analysis-review.yml GH_PAT=… ./scripts/dispatch_github_workflow.sh
```

Requires `CURSOR_API_KEY` in GitHub repo secrets. Skips cleanly if inputs are thin.

### 5. Ops monitor — daily health + email (~07:45 UTC)

Runs after Mon/Wed/Fri ingest loop and before weekday paper orchestrator (~08:20).
Schedule: `45 7 * * *`.

```bash
WORKFLOW=ops-monitor.yml GH_PAT=… ./scripts/dispatch_github_workflow.sh
```

Sends SMTP summary on warn/fail or when auto-fixes run. Same-day skip on duplicate success.

### 6. Data backup — Sunday tier-1 snapshot (~12:30 UTC)

After the Sunday email bundle commits `docs/data/`. Schedule: `30 12 * * 0`.

```bash
WORKFLOW=data-backup.yml GH_PAT=… ./scripts/dispatch_github_workflow.sh
```

Creates `output/backups/ftse-tier1-*.tar.gz` as a GitHub Actions artifact (90-day retention).
Optional `BACKUP_S3_URI` + AWS secrets for off-repo copy. See [`data-backup.md`](data-backup.md).

### Generic dispatch (any workflow)

```bash
WORKFLOW=ingest-loop.yml GH_PAT=… ./scripts/dispatch_github_workflow.sh
# with inputs:
WORKFLOW=ingest-loop.yml INPUTS_JSON='{"force":"true"}' GH_PAT=… ./scripts/dispatch_github_workflow.sh
```

Equivalent curl:

```bash
curl -sS -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer $GH_PAT" \
  https://api.github.com/repos/jamiefuller320/value_investor/actions/workflows/WORKFLOW.yml/dispatches \
  -d '{"ref":"main"}'
```

### `repository_dispatch` alternative (orchestrator only)

```bash
MODE=repository_dispatch SUITE=sunday GH_PAT=… ./scripts/dispatch_orchestrator.sh
```

Payload type must be `automation-orchestrator`.

## Orchestrator behaviour (in-repo)

| Layer | Behaviour |
|-------|-----------|
| Primary schedules | Sun 06:17, daily surplus 05:30, weekdays 08:17 UTC |
| Catch-up schedules | Sun 09:17 + 12:17; weekdays 11:17 UTC |
| Same-day skip | Catch-up does **not** re-run children that already succeeded today |
| Manual / API | `workflow_dispatch` and `repository_dispatch` (`automation-orchestrator`) |

Force a full re-run: Actions UI → Orchestrator → `force=true`, or `FORCE=true` with the script above.

## Checklist — adding a new scheduled workflow

1. Implement `workflow_dispatch` (required) and optional `schedule:` backup.
2. Add **same-day skip** if duplicate runs are wasteful or unsafe.
3. Document the cron-job.org expression in this file + workflow ops doc.
4. Add `scripts/dispatch_github_workflow.sh` example or orchestrator child dispatch.
5. Update `automation_status.py` `WORKFLOW_SCHEDULES` cadence string.
6. Test once via cron-job.org; confirm `workflow_dispatch` run in Actions.

## Verify after a quiet Sunday

```bash
gh run list --workflow=automation-orchestrator.yml --limit 5
gh run list --workflow=email-report.yml --limit 3
gh run list --workflow=analysis-review.yml --limit 3
gh run list --workflow=ops-monitor.yml --limit 3
gh run list --workflow=data-backup.yml --limit 3
gh run list --workflow=ingest-loop.yml --limit 3
```

Expect successful runs without manual **Run workflow** clicks.

## Failure emails that are not regressions

Red runs caused by `startup_failure`, runner queue timeouts, or superseded PR CI are documented in [github-actions-flakes.md](github-actions-flakes.md).
