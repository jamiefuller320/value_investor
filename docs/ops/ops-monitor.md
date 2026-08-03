# Ops monitor

Daily operational health checks for cron-driven workflows, committed
artifacts, ingest stall detection, and the engineering queue.

**Safe auto-fixes** (when `--apply` / default in CI):

- Reconcile orphaned `pr_open` engineering tasks (no matching open PR)
- Normalize corrupt `ingest_health_log.json` (with sibling backup)
- Micro-compile ingest engineering tasks when buy-tier filing ingest is stalled
- Quarantine corrupt or duplicate backtest history snapshots (see [backtest-health.md](backtest-health.md))
- Reconcile engineering queue sync issues and redispatch when the agent failed on a stale task id (see [engineering-sync.md](engineering-sync.md))

**Supervised follow-ons** (not automatic code changes):

- Draft `ops` engineering tasks for unresolved failures (workflow overdue, etc.)
- Dispatch `engineering-queue.yml` when the queue is ready for the next PR

## When it runs

| Trigger | Schedule |
|---------|----------|
| **cron-job.org (primary)** | Daily **07:45 UTC** (`45 7 * * *`) |
| GitHub cron (backup) | Same expression |
| Manual | Actions → **FTSE Ops Monitor** → Run workflow |

External dispatch:

```bash
WORKFLOW=ops-monitor.yml GH_PAT=… ./scripts/dispatch_github_workflow.sh
```

Runs after the Mon/Wed/Fri ingest loop (~07:05) and before weekday paper
orchestrator (~08:20). Same-day skip — a second successful run the same UTC
day exits quickly unless `email_always=true`.

### cron-job.org setup (one-time)

Register the scheduled HTTP job on cron-job.org (daily **07:45 UTC**). This is
separate from the GitHub `workflow_dispatch` curl above — cron-job.org calls
GitHub on your behalf.

**curl (recommended one-liner setup):**

```bash
export CRONJOB_API_KEY=…   # cron-job.org → Settings → API
export GH_PAT=…            # fine-grained PAT, Actions: Read and write on this repo

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
          "Authorization": "Bearer '"$GH_PAT"'"
        },
        "body": "{\"ref\":\"main\"}"
      }
    }
  }'
```

Response is `{"jobId":12345}` on success. Then trigger once from the cron-job.org
console (**Run now**) or wait for the next 07:45 UTC slot.

**Optional bulk import** (all production jobs — idempotent by title):

```bash
CRONJOB_API_KEY=… GH_PAT=… ./scripts/import_cron_jobs.py --all
# or just ops monitor:
CRONJOB_API_KEY=… GH_PAT=… ./scripts/import_cron_jobs.py --job ops-monitor
```

Dry-run payloads: `./scripts/import_cron_jobs.py --job ops-monitor --dry-run --json`

**Manual UI** (alternative): [cron-job.org](https://cron-job.org) → **Create cronjob**

1. **Title:** `FTSE ops monitor (daily)`
2. **URL:** `https://api.github.com/repos/jamiefuller320/value_investor/actions/workflows/ops-monitor.yml/dispatches`
3. **Schedule:** custom `45 7 * * *` (daily 07:45 UTC)
4. **Request method:** `POST`
5. **Request headers:** `Accept: application/vnd.github+json`, `Authorization: Bearer <GH_PAT>`
6. **Request body:** `{"ref":"main"}`
7. **Timezone:** UTC

Verify:

```bash
gh run list --workflow=ops-monitor.yml --limit 3
```

Expect a successful `workflow_dispatch` run; `docs/data/ops_status.json` updates on
warn/fail or when auto-fixes run.

See [orchestrator-cron.md](orchestrator-cron.md) for the repo-wide scheduling policy.

## Artifacts

| File | Purpose |
|------|---------|
| `docs/data/ops_status.json` | Latest findings, auto-fixes, workflow freshness |
| `docs/data/ops_monitor_log.json` | Rolling daily run index (90 entries) |
| `docs/data/backtest_health.json` | Backtest history audit and readiness (see [backtest-health.md](backtest-health.md)) |

## CLI

```bash
# Check only (no writes beyond ops_status.json)
ftse-ops-monitor run --no-apply --no-draft

# Full run + email on warn/fail/auto-fix
ftse-ops-monitor run --email

# CI: do not fail the workflow when only workflow-overdue checks are red
ftse-ops-monitor run --allow-workflow-stale-exit-zero

# Email the saved report
ftse-ops-monitor email
```

Requires `GITHUB_TOKEN` / `GH_TOKEN` for workflow freshness checks and
`SMTP_*` + `EMAIL_TO` for email delivery.

### Workflow freshness thresholds

| Workflow | Expected | Stale when |
|----------|----------|------------|
| Ingest loop | Mon/Wed/Fri | No success within 30h on scheduled days |
| Orchestrator | Daily | No success within 28h |

When the orchestrator or a Sunday quiet-bundle child (`library-grow`,
`library-model-review`, `email-report`) is **actively running**, overdue findings
for those workflows are downgraded to `warn` and annotated with
`Recovery bundle in flight`.

The GitHub Actions workflow passes `--allow-workflow-stale-exit-zero` so a
morning run that reports orchestrator staleness before catch-up still commits
`ops_status.json` and sends email without failing the job.

| Engineering queue | Weekdays | **3h** when open/pr_open tasks exist; **26h** when the queue is fully idle |
| Analysis review | Sunday | No success within 36h |

Engineering queue reliability depends on external cron (`engineering-queue` job in
`import_cron_jobs.py`); GitHub `schedule` is backup only.

## Email policy

By default the workflow sends email when:

- Overall status is `warn` or `fail`, or
- Any auto-fix ran

Use workflow input `email_always=true` or `ftse-ops-monitor run --email-always`
for a daily digest regardless of status.

## Guardrails

- Does **not** dispatch `engineering-agent` directly — only `engineering-queue`
- Does **not** change paper books, screen signals, or decision-review knobs
- Code fixes for drafted `ops` tasks follow the normal supervised engineering PR path

## Engineering queue recovery

`ftse-engineering recover-queue` (hourly via `engineering-queue.yml` and daily via ops monitor):

| Situation | Action |
|-----------|--------|
| `pr_open` but PR closed / missing | Reopen → `open` (auto-retry) |
| `failed` with retries left + cooldown elapsed | Reopen → `open` |
| `failed` after max agent retries | Park → `parked` (manual review) |
| `pr_open` with CI red for 48h+ | Park → `parked` (unblocks queue; PR stays for you) |

List parked tasks: `ftse-engineering list-parked`

To resume a parked task manually, set status back to `open` in `engineering_tasks.json` or add a fresh task.

See also: [`orchestrator-cron.md`](orchestrator-cron.md), [`analysis-review.md`](analysis-review.md), [`backtest-health.md`](backtest-health.md), [`engineering-sync.md`](engineering-sync.md).
