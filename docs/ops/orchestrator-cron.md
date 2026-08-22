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

**PAT:** fine-grained, **Actions: Read and write** on this repo only. Store as
`WORKFLOW_DISPATCH_PAT` on the cron host and in Cursor Cloud secrets — never commit
it. Avoid using `GH_TOKEN` alone in Cursor; it may receive the `ghs_…` integration
token instead of your user PAT.

**Helper scripts:**

- `scripts/dispatch_orchestrator.sh` — Sunday / weekday paper / surplus suites
- `scripts/dispatch_github_workflow.sh` — any single workflow file
- `scripts/import_cron_jobs.py` — bulk import/update cron-job.org jobs via API
- `scripts/sync_euro_ingest_cron.py` — toggle euro_depth ingest + weekday ladder crons from completion gate

## Coverage matrix

| Workflow | Production trigger | External cron (cron-job.org) | GitHub `schedule` backup |
|----------|-------------------|------------------------------|---------------------------|
| `automation-orchestrator.yml` | External **primary** | Sun 06:20 `SUITE=sunday`; Mon–Fri **08:25 UTC** `SUITE=weekday_paper` | Sun 06/09/12, daily 05:30, weekdays **08:25 / 11:25** |
| `email-report.yml` | Via orchestrator | ↑ (orchestrator dispatches) | None (by design) |
| `library-grow.yml` | Via orchestrator | ↑ | None |
| `library-model-review.yml` | Via orchestrator | ↑ | None |
| `paper-auto.yml` | Via orchestrator weekdays | ↑ | None |
| `ingest-loop.yml` | External **primary** | Mon–Fri **07:05 + 10:05** → two batches (`max_targets=12`) | Mon–Fri 07:05 + 10:05 |
| `analysis-review.yml` | External **primary** | `35 10 * * 0` (± optional `35 12 * * 0`) → `analysis-review.yml` | Sun 10:35 |
| `paper-learning-review.yml` | External **primary** | `45 10 * * 0` → `paper-learning-review.yml` | Sun 10:45 |
| `ops-monitor.yml` | External **primary** | `45 7 * * *` → `ops-monitor.yml` | Daily 07:45 |
| `ci-main-nightly.yml` | External **primary** | `30 7 * * *` → `ci-main-nightly.yml` | Daily 07:30 |
| `data-backup.yml` | External **primary** | `30 12 * * 0` → `data-backup.yml` | Sun 12:30 (after email) |
| `engineering-queue.yml` | External **primary** | `15 * * * 1-5` → `engineering-queue.yml` (hourly :15 UTC) | Hourly weekdays (backup) |
| `euro-ingest-loop.yml` | External **primary** | Mon–Fri **07:15 + 10:15** → `euro-ingest-loop.yml` (throttled by completion gate) | Mon–Fri 07:15 + 10:15 |
| `automation-orchestrator.yml` (`ladder_only`) | External **primary** (sprint) | Mon–Fri **06:50** → `suite=ladder_only` (disabled when Phase 3 + parity idle) | No |
| `engineering-agent.yml` | Queue / manual | No | No |
| `ci.yml` / `pages.yml` | Push to `docs/**` on `main`; **also** `email-report.yml` dispatches after dashboard commit (`[skip ci]` blocks push-triggered Pages) | No | No |

## One-time external cron setup

Two layers:

1. **Register on cron-job.org** — `PUT https://api.cron-job.org/jobs` (curl below or import script)
2. **What each job calls** — GitHub `workflow_dispatch` (curl in [Generic dispatch](#generic-dispatch-any-workflow))

### Register jobs on cron-job.org (curl)

`CRONJOB_API_KEY` from [cron-job.org](https://cron-job.org) → Settings → API.
`WORKFLOW_DISPATCH_PAT` is the fine-grained PAT with **Actions: Read and write** on this repo.

**Data backup** (Sunday 12:30 UTC):

```bash
export CRONJOB_API_KEY=…
export WORKFLOW_DISPATCH_PAT=…

curl -sS -X PUT 'https://api.cron-job.org/jobs' \
  -H "Authorization: Bearer $CRONJOB_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{
    "job": {
      "title": "FTSE data backup (Sunday)",
      "url": "https://api.github.com/repos/jamiefuller320/value_investor/actions/workflows/data-backup.yml/dispatches",
      "enabled": true,
      "saveResponses": true,
      "requestMethod": 1,
      "schedule": {
        "timezone": "UTC",
        "expiresAt": 0,
        "hours": [12],
        "minutes": [30],
        "mdays": [-1],
        "months": [-1],
        "wdays": [0]
      },
      "extendedData": {
        "headers": {
          "Accept": "application/vnd.github+json",
          "Authorization": "Bearer '"$WORKFLOW_DISPATCH_PAT"'"
        },
        "body": "{\"ref\":\"main\"}"
      }
    }
  }'
```

**Ops monitor** (daily 07:45 UTC) — same pattern; change `title`, `hours`/`minutes`/`wdays`, and workflow URL:

```bash
curl -sS -X PUT 'https://api.cron-job.org/jobs' \
  -H "Authorization: Bearer $CRONJOB_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{
    "job": {
      "title": "FTSE ops monitor (daily)",
      "url": "https://api.github.com/repos/jamiefuller320/value_investor/actions/workflows/ops-monitor.yml/dispatches",
      "enabled": true,
      "saveResponses": true,
      "requestMethod": 1,
      "schedule": {
        "timezone": "UTC",
        "expiresAt": 0,
        "hours": [7],
        "minutes": [45],
        "mdays": [-1],
        "months": [-1],
        "wdays": [-1]
      },
      "extendedData": {
        "headers": {
          "Accept": "application/vnd.github+json",
          "Authorization": "Bearer '"$WORKFLOW_DISPATCH_PAT"'"
        },
        "body": "{\"ref\":\"main\"}"
      }
    }
  }'
```

Schedule fields: `wdays` `0`=Sunday … `6`=Saturday, `[-1]`=every day; `hours`/`minutes` are UTC when `timezone` is `UTC`. `requestMethod` `1` = POST.

**Optional bulk import** (all six production jobs — idempotent by title):

```bash
CRONJOB_API_KEY=… WORKFLOW_DISPATCH_PAT=… ./scripts/import_cron_jobs.py --all
```

Job keys: `orchestrator-sunday`, `orchestrator-weekday-paper`, `ingest-loop-morning`,
`ingest-loop-afternoon`,
`analysis-review`, `ops-monitor`, `data-backup`. Dry-run: `--dry-run --json`.

Manual per-job dispatch examples (what cron-job.org calls) below.

### 1. Orchestrator — Sunday quiet bundle (06:20 UTC)

```bash
export WORKFLOW_DISPATCH_PAT=…
SUITE=sunday ./scripts/dispatch_orchestrator.sh
```

Optional Sunday catch-up: repeat at **09:20 UTC** (`SUITE=sunday` or `SUITE=catchup_today`).

### 2. Orchestrator — weekday paper (08:25 UTC Mon–Fri)

London settle is **09:15** local (75 min after 08:00 open). Primary dispatch must be
**≥08:25 UTC** so BST runs land after settle. If cron-job.org was set to 08:20
**Europe/London** by mistake, paper-auto would fire pre-settle and never trade.

```bash
WORKFLOW_DISPATCH_PAT=… SUITE=weekday_paper ./scripts/dispatch_orchestrator.sh
```

After merging scheduling fixes, refresh the external cron:

```bash
WORKFLOW_DISPATCH_PAT=… CRONJOB_API_KEY=… ./scripts/import_cron_jobs.py --job orchestrator-weekday-paper
```

### 3. Ingest loop — weekday two batches per day

Schedules: **07:05** and **10:05 UTC** on **Mon–Fri** (`ingest-loop-morning` /
`ingest-loop-afternoon` cron-job.org keys). Each dispatch uses `max_targets=12`;
the workflow gate allows **up to two successful runs per UTC day** (morning +
afternoon), not one.

Volume and budget context: [`market-scrutiny.md`](market-scrutiny.md).

```bash
WORKFLOW=ingest-loop.yml INPUTS_JSON='{"max_targets":"12"}' WORKFLOW_DISPATCH_PAT=… ./scripts/dispatch_github_workflow.sh
```

Refresh external cron after merge:

```bash
WORKFLOW_DISPATCH_PAT=… CRONJOB_API_KEY=… ./scripts/import_cron_jobs.py \
  --job ingest-loop-morning --job ingest-loop-afternoon
```

Disable the legacy single job **“FTSE ingest loop (Mon/Wed/Fri)”** on cron-job.org
if it still exists (superseded by morning + afternoon jobs).

Same-day gate — safe alongside GitHub `0 7` / `0 10` schedules; skips only after
two successes or while another run is active.

#### Why weekday (Mon–Fri) ingest?

| Factor | Notes |
|--------|--------|
| **FTSE gap closure** | 11 unmeasured buy-tier tickers need bootstrap slots; Tue/Thu add capacity without waiting for Mon/Wed/Fri |
| **Screen cadence** | Sunday screen refreshes buy-tier; weekday ingest deepens filings against `latest.json` |
| **Cost** | Ingest-loop uses CH/RNS/API fetch — **not** `weekly_ops` Cursor spend |
| **Capacity** | 5 days × 2 runs × 12 targets = **120 ticker-slots/week** (see `market-scrutiny.md`) |

The **10:05 UTC afternoon batch** continues coverage after the morning slot (~12
targets + 6 bootstrap seeds each; ~25 min budget per run). Ops monitor at
07:45 UTC still flags buy-tier ingest stalls and can micro-compile ingest tasks
on any weekday when zero-body counts stop improving.

### 4. Analysis review — Sunday after email bundle (~10:35 UTC)

Run **after** the Sunday screen commits `docs/data/` (email via orchestrator often
finishes 08:00–11:00 UTC). Schedule: `35 10 * * 0` (optional backup `35 12 * * 0`).

```bash
WORKFLOW=analysis-review.yml WORKFLOW_DISPATCH_PAT=… ./scripts/dispatch_github_workflow.sh
```

Requires `CURSOR_API_KEY` in GitHub repo secrets. Skips cleanly if inputs are thin.

### 5. Ops monitor — daily health + email (~07:45 UTC)

Runs after Mon/Wed/Fri ingest loop and before weekday paper orchestrator (~08:20).
Schedule: `45 7 * * *`.

```bash
WORKFLOW=ops-monitor.yml WORKFLOW_DISPATCH_PAT=… ./scripts/dispatch_github_workflow.sh
```

Sends SMTP summary on warn/fail or when auto-fixes run. Same-day skip on duplicate success.

### 6. Data backup — Sunday tier-1 snapshot (~12:30 UTC)

After the Sunday email bundle commits `docs/data/`. Schedule: `30 12 * * 0`.

```bash
WORKFLOW=data-backup.yml WORKFLOW_DISPATCH_PAT=… ./scripts/dispatch_github_workflow.sh
```

Creates `output/backups/ftse-tier1-*.tar.gz` as a GitHub Actions artifact (90-day retention).
Optional `BACKUP_S3_URI` + AWS secrets for off-repo copy. See [`data-backup.md`](data-backup.md).

### Generic dispatch (any workflow)

```bash
WORKFLOW=ingest-loop.yml INPUTS_JSON='{"max_targets":"12"}' WORKFLOW_DISPATCH_PAT=… ./scripts/dispatch_github_workflow.sh
# with inputs:
WORKFLOW=ingest-loop.yml INPUTS_JSON='{"force":"true","max_targets":"12"}' WORKFLOW_DISPATCH_PAT=… ./scripts/dispatch_github_workflow.sh
```

Equivalent curl:

```bash
curl -sS -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer $WORKFLOW_DISPATCH_PAT" \
  https://api.github.com/repos/jamiefuller320/value_investor/actions/workflows/WORKFLOW.yml/dispatches \
  -d '{"ref":"main"}'
```

### `repository_dispatch` alternative (orchestrator only)

```bash
MODE=repository_dispatch SUITE=sunday WORKFLOW_DISPATCH_PAT=… ./scripts/dispatch_orchestrator.sh
```

Payload type must be `automation-orchestrator`.

## Orchestrator behaviour (in-repo)

| Layer | Behaviour |
|-------|-----------|
| Primary schedules | Sun 06:17, daily surplus 05:30, weekdays **08:25** UTC |
| Catch-up schedules | Sun 09:17 + 12:17; weekdays **11:25** UTC |
| Duplicate-run gate | Skip a new orchestrator run when another is `in_progress`/`queued`/`waiting` (unless `force=true`) |
| Same-day skip | Catch-up does **not** re-run children that already **succeeded or are active** today (`busyToday`). **paper-auto** is special: a pre-settle success (`last_run.gate.after_settle=false`) does **not** block a post-settle re-dispatch. |
| Manual / API | `workflow_dispatch` and `repository_dispatch` (`automation-orchestrator`) |

Force a full re-run: Actions UI → Orchestrator → `force=true`, or `FORCE=true` with the script above.

## Checklist — adding a new scheduled workflow

1. Implement `workflow_dispatch` (required) and optional `schedule:` backup.
2. Add **same-day skip** if duplicate runs are wasteful or unsafe.
3. Document the cron-job.org expression in this file + workflow ops doc.
4. Add `scripts/dispatch_github_workflow.sh` example or orchestrator child dispatch.
5. Update `automation_status.py` `WORKFLOW_SCHEDULES` cadence string.
6. Test once via cron-job.org; confirm `workflow_dispatch` run in Actions.

## Mid-week analysis refresh (after engineering merges)

When the weekday engineering queue has drained and merged code should appear on the
dashboard **Analysis** tab before the next Sunday screen, use
[accelerated-review-cycle.md](accelerated-review-cycle.md) (`SUITE=email_only` +
`FORCE=true`). First planned use: after the next baseline Sunday cycle (week of
2026-08-03).

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
