# Data backup & restore

Policy for protecting committed `docs/data` assets that are expensive to
re-fetch or re-agent. GitHub remains the **primary** store; this adds
**off-repo snapshots** and a **restore drill**.

Related: [`architecture.md`](../architecture.md), [`orchestrator-cron.md`](orchestrator-cron.md).

## Recovery objectives

| Tier | RPO (max loss) | RTO (target restore) | Mechanism |
|------|----------------|----------------------|-----------|
| **Tier 1** | 7 days (weekly Sunday snapshot) | &lt; 1 hour manual | `ftse-data-backup` + email + optional S3 |
| **Tier 2** | 7 days if `--include-tier2` | Same session as tier 1 | Optional in snapshot |
| **GitHub `main`** | Last commit | Minutes (clone/checkout) | Implicit backup |

RPO improves to **24h** if you add a daily cron (optional); Sunday-after-email is the default.

## Data tiers

### Tier 1 — snapshot always (expensive to replace)

| Path | Why |
|------|-----|
| `docs/data/library/` | Offline PIT fundamentals & screen-lite history |
| `docs/data/history/` | Weekly run snapshots for backtest / historical replay |
| `docs/data/paper_automation/` | Paper learning books & track state |
| `docs/data/research/` | Memo sources (filing bodies, news batches) |

### Tier 2 — optional (`--include-tier2`)

| Path | Why |
|------|-----|
| `docs/data/engineering_tasks.json` | Queue state (small, regenerable partly) |
| `docs/data/latest.json` | Dashboard bundle (rebuild from Sunday screen) |
| `docs/data/research_model_suggestions.json` | Suggestions ledger |

### Ephemeral — not backed up

| Path | Why |
|------|-----|
| `output/` | Rebuilt each run; gitignored |
| `docs/data/ops_*.json`, ingest logs | Operational telemetry |

Retention for history and local output pruning is handled in `storage.py`
(**3-year** window for run snapshots).

## Commands

```bash
# Create tarball + manifest under output/backups/ (gitignored)
ftse-data-backup snapshot

# Include tier-2 JSON files
ftse-data-backup snapshot --include-tier2

# Upload to S3 when BACKUP_S3_URI is set (requires AWS CLI + credentials)
ftse-data-backup snapshot --upload

# Email manifest + chunked archive off-GitHub (default: intellaigence101@gmail.com)
ftse-data-backup snapshot --email

# Reassemble emailed chunks into a tarball
ftse-data-backup reassemble --output restored.tar.gz ftse-tier1-*.part*

# List local snapshots
ftse-data-backup list

# Verify checksum
ftse-data-backup verify output/backups/ftse-tier1-YYYYMMDDTHHMMSSZ.tar.gz

# Restore into current repo (merge overwrite)
ftse-data-backup restore output/backups/ftse-tier1-....tar.gz

# Dry-run restore
ftse-data-backup restore output/backups/ftse-tier1-....tar.gz --dry-run

# Post-restore drill (tier paths + history → output/)
ftse-data-backup drill
```

## Scheduling

| Trigger | When | Notes |
|---------|------|-------|
| **cron-job.org (primary)** | Sunday **12:30 UTC** (`30 12 * * 0`) | After Sunday email bundle commits `docs/data/` |
| **GitHub cron (backup)** | Same expression | Same-day skip — safe alongside external cron |
| **Manual** | Any time | Actions → **FTSE Data Backup** → Run workflow |

External dispatch (same `GH_PAT` as orchestrator / ingest / ops monitor):

```bash
WORKFLOW=data-backup.yml GH_PAT=… ./scripts/dispatch_github_workflow.sh
```

Same-day skip: a second successful run the same UTC day exits quickly unless
`force=true`.

### cron-job.org setup (one-time)

Register the scheduled HTTP job on cron-job.org (Sunday **12:30 UTC**). This is
separate from the GitHub `workflow_dispatch` curl in
[orchestrator-cron.md](orchestrator-cron.md) — cron-job.org calls GitHub on your
behalf.

**curl (recommended one-liner setup):**

```bash
export CRONJOB_API_KEY=…   # cron-job.org → Settings → API
export GH_PAT=…            # fine-grained PAT, Actions: Read and write on this repo

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
          "Authorization": "Bearer '"$GH_PAT"'"
        },
        "body": "{\"ref\":\"main\"}"
      }
    }
  }'
```

Response is `{"jobId":12345}` on success. Then trigger once from the cron-job.org
console (**Run now**) or wait for Sunday.

**Optional bulk import** (all production jobs — idempotent by title):

```bash
CRONJOB_API_KEY=… GH_PAT=… ./scripts/import_cron_jobs.py --all
# or just data backup:
CRONJOB_API_KEY=… GH_PAT=… ./scripts/import_cron_jobs.py --job data-backup
```

Dry-run payloads: `./scripts/import_cron_jobs.py --job data-backup --dry-run --json`

**Manual UI** (alternative): [cron-job.org](https://cron-job.org) → **Create cronjob**

1. **Title:** `FTSE data backup (Sunday)`
2. **URL:** `https://api.github.com/repos/jamiefuller320/value_investor/actions/workflows/data-backup.yml/dispatches`
3. **Schedule:** custom `30 12 * * 0` (Sunday 12:30 UTC)
4. **Request method:** `POST`
5. **Request headers:** `Accept: application/vnd.github+json`, `Authorization: Bearer <GH_PAT>`
6. **Request body:** `{"ref":"main"}`
7. **Timezone:** UTC

Verify:

```bash
gh run list --workflow=data-backup.yml --limit 3
```

Expect a successful `workflow_dispatch` run with artifact `ftse-tier1-data-backup`.

See [orchestrator-cron.md](orchestrator-cron.md) for the repo-wide scheduling policy.

### S3 upload (optional)

Set repository secrets / env:

| Variable | Example |
|----------|---------|
| `BACKUP_S3_URI` | `s3://my-bucket/ftse-value-investor/backups/` |
| `AWS_ACCESS_KEY_ID` | … |
| `AWS_SECRET_ACCESS_KEY` | … |
| `AWS_DEFAULT_REGION` | `eu-west-2` |

Lifecycle rule on the bucket: keep **weekly** objects 90 days, **monthly** pins 1 year.

### Email off-GitHub copy (default)

Weekly CI runs email the manifest plus chunked archive to **`intellaigence101@gmail.com`**
(override with `BACKUP_EMAIL_TO`). Uses the same SMTP secrets as the Sunday screen
(`SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`).

Snapshots are ~60MB compressed today — above Gmail’s single-attachment limit — so the
workflow sends **multiple emails** (~15MB parts) plus one manifest message with restore
instructions. Reassemble locally:

```bash
ftse-data-backup reassemble --output restored.tar.gz ~/Downloads/ftse-tier1-*.part*
ftse-data-backup verify restored.tar.gz
ftse-data-backup restore restored.tar.gz
```

Optional GitHub secret `BACKUP_EMAIL_TO` overrides the default mailbox.

## Restore procedure (quarterly drill)

1. Clone a clean copy of the repo (or use a worktree).
2. Download latest snapshot (email chunks, S3, GitHub Actions artifact, or local `output/backups`).
3. If from email: `ftse-data-backup reassemble --output archive.tar.gz *.part*`
4. `ftse-data-backup verify <archive.tar.gz>`
5. `ftse-data-backup restore <archive.tar.gz>`
6. `ftse-data-backup drill`
7. `ftse-preflight` and `python3 -m pytest tests/test_historical_analysis.py -q` (smoke)

## What GitHub already gives you

- Every Sunday `email-report` commit pushes fresh `docs/data/**` to `main`.
- Git history is the first recovery lever (revert bad commits, recover files).
- Off-repo snapshots protect against **repo-wide** incidents and make restore drills faster than parsing git blobs.

## Growth watchpoints

| Signal | Action |
|--------|--------|
| Committed `docs/data` &gt; **500MB** | Enable S3 upload; review library thinning |
| Committed `docs/data` &gt; **1GB** | Monthly restore drill mandatory; consider excluding re-fetchable blobs from git |
| Snapshot &gt; **2GB** | Split library vs live research archives |
