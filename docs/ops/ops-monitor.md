# Ops monitor

Daily operational health checks for cron-driven workflows, committed
artifacts, ingest stall detection, and the engineering queue.

**Safe auto-fixes** (when `--apply` / default in CI):

- Reconcile orphaned `pr_open` engineering tasks (no matching open PR)
- Normalize corrupt `ingest_health_log.json` (with sibling backup)
- Micro-compile ingest engineering tasks when buy-tier filing ingest is stalled

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

## Artifacts

| File | Purpose |
|------|---------|
| `docs/data/ops_status.json` | Latest findings, auto-fixes, workflow freshness |
| `docs/data/ops_monitor_log.json` | Rolling daily run index (90 entries) |

## CLI

```bash
# Check only (no writes beyond ops_status.json)
ftse-ops-monitor run --no-apply --no-draft

# Full run + email on warn/fail/auto-fix
ftse-ops-monitor run --email

# Email the saved report
ftse-ops-monitor email
```

Requires `GITHUB_TOKEN` / `GH_TOKEN` for workflow freshness checks and
`SMTP_*` + `EMAIL_TO` for email delivery.

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

See also: [`orchestrator-cron.md`](orchestrator-cron.md), [`analysis-review.md`](analysis-review.md).
