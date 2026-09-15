# Ops monitor

Daily operational health checks for cron-driven workflows, committed
artifacts, ingest stall detection, and the engineering queue.

**Heal → re-verify → report** (when `--apply` / default in CI):

1. Detect findings (artifacts, ingest health, workflows, engineering queue, Phase B
   structured-verdict producer progress, claimed-vs-landed indicator integrity
   (**L389**), …)
2. Apply **safe auto-fixes** (below)
3. **Re-run detection** so overall status reflects post-fix truth
4. Draft supervised tasks / send email only for **unfixed** warn/fail

**Safe auto-fixes:**

- Reconcile orphaned `pr_open` engineering tasks (no matching open PR)
- Normalize corrupt `ingest_health_log.json` (with sibling backup)
- Micro-compile ingest engineering tasks when buy-tier filing ingest is stalled
- Grade parked engineering tasks and auto-cancel duplicates of merged work
- Quarantine corrupt or duplicate backtest history snapshots (see [backtest-health.md](backtest-health.md))
- Reconcile engineering queue sync issues and redispatch when the agent failed on a stale task id (see [engineering-sync.md](engineering-sync.md))
- Suppress “recent workflow failure” alerts while a recovery run for that workflow is already in flight
- Suppress workflow-overdue findings while a run is in flight, or before that workflow’s `WORKFLOW_EMAIL_READY_UTC` slot (Monday morning cliff / pending primary cron)
- `workflow_dispatch` overdue **ingest-loop** / **paper-auto** after email-ready when no run is active

**Supervised follow-ons** (not automatic code changes):

- Draft `ops` engineering tasks for unresolved failures (workflow overdue outside auto-dispatch, etc.)
- Run so-what auto-queue for no-judgment enforcement gaps (see [so-what-gap-closure.md](so-what-gap-closure.md))
- Dispatch `engineering-queue.yml` when the queue is ready for the next PR

Workflow failure **reruns** (library ladder guarded rerun, CI fix, etc.) stay in their
dedicated `workflow_run` responders — ops monitor does not wait on long GitHub jobs
before emailing. Healed local issues and in-flight recoveries are recorded in
`ops_status.json` but do not generate alert email. Overdue ingest/paper dispatches are
fire-and-forget; the next ops-monitor pass confirms success.

## When it runs

| Trigger | Schedule |
|---------|----------|
| **cron-job.org (primary)** | Daily **07:45 UTC** (`45 7 * * *`) morning + **13:15 UTC** (`15 13 * * *`) catch-up |
| GitHub cron (backup) | Same expressions |
| Manual | Actions → **FTSE Ops Monitor** → Run workflow |

External dispatch:

```bash
WORKFLOW=ops-monitor.yml WORKFLOW_DISPATCH_PAT=… ./scripts/dispatch_github_workflow.sh
```

Runs after the Mon/Wed/Fri ingest loop (~07:05) and before weekday paper
orchestrator (~08:20). Morning may **defer email** when remaining findings are
still expected to clear later the same day (Sunday analysis-review / data-backup
slots, quiet-bundle recovery still in flight, dashboard waiting on email-report,
paper learning-track coverage before 10:00 UTC).
Same-day skip applies only after a run that did **not** defer email — the 13:15
catch-up re-checks and emails only if issues remain.

Artifact commit uses `scripts/gha_commit_ops_monitor.sh` → shared
`scripts/gha_commit_artifacts.sh` (fetch + retry; also used by email-report and
library-grow). Status files always overlay; `engineering_tasks.json` / health
logs overlay only when `main` has not changed them since checkout. The workflow
commits those artifacts even when `ftse-ops-monitor` exits non-zero, then fails
the job afterward so a red finding cannot leave `ops_status.json` stale.

### Email deferral (day-complete gate)

Alert email is skipped when **every** unfixed warn/fail is still “pending today”:

| Finding class | Deferred until |
|---------------|----------------|
| Workflow overdue before `WORKFLOW_EMAIL_READY_UTC` for that workflow | After that wall-clock time (e.g. analysis-review 11:00, data-backup 13:00) |
| Paper learning-track coverage (`category=paper`) on a weekday before 10:00 UTC | After paper-auto email-ready (10:00 UTC); 13:15 catch-up is the actionable pass |
| Recovery / quiet bundle in flight | Active recovery run finishes |
| Dashboard stale while today's email-report still pending | email-report succeeds today |

`ops_status.json` records `email_deferred` + `email_defer_reasons`. Ops engineering
tasks are **not** drafted for deferred findings. Use `email_always=true` / `--email-always`
to force a digest anyway.

### cron-job.org setup (one-time)

Register the scheduled HTTP job on cron-job.org (daily **07:45 UTC**). This is
separate from the GitHub `workflow_dispatch` curl above — cron-job.org calls
GitHub on your behalf.

**curl (recommended one-liner setup):**

```bash
export CRONJOB_API_KEY=…   # cron-job.org → Settings → API
export WORKFLOW_DISPATCH_PAT=…            # fine-grained PAT, Actions: Read and write on this repo

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

Response is `{"jobId":12345}` on success. Then trigger once from the cron-job.org
console (**Run now**) or wait for the next 07:45 UTC slot.

**Optional bulk import** (all production jobs — idempotent by title):

```bash
CRONJOB_API_KEY=… WORKFLOW_DISPATCH_PAT=… ./scripts/import_cron_jobs.py --all
# or just ops monitor:
CRONJOB_API_KEY=… WORKFLOW_DISPATCH_PAT=… ./scripts/import_cron_jobs.py --job ops-monitor
```

Dry-run payloads: `./scripts/import_cron_jobs.py --job ops-monitor --dry-run --json`

**Manual UI** (alternative): [cron-job.org](https://cron-job.org) → **Create cronjob**

1. **Title:** `FTSE ops monitor (daily)`
2. **URL:** `https://api.github.com/repos/jamiefuller320/value_investor/actions/workflows/ops-monitor.yml/dispatches`
3. **Schedule:** custom `45 7 * * *` (daily 07:45 UTC)
4. **Request method:** `POST`
5. **Request headers:** `Accept: application/vnd.github+json`, `Authorization: Bearer <WORKFLOW_DISPATCH_PAT>`
6. **Request body:** `{"ref":"main"}`
7. **Timezone:** UTC

Verify:

```bash
gh run list --workflow=ops-monitor.yml --limit 3
```

Expect a successful `workflow_dispatch` run; `docs/data/ops_status.json` updates each
run (including healed-only mornings).

See [orchestrator-cron.md](orchestrator-cron.md) for the repo-wide scheduling policy.

### Parked engineering tasks

The daily ops monitor **grades** parked tasks (no separate housekeeping loop):

| `parked_policy` | Ops email alert? | Auto action |
|-----------------|------------------|-------------|
| `duplicate` (of merged task) | No | Cancel task when `duplicate_of` is merged |
| `no_diff_cap` | No | Annotate policy only |
| `ci_blocked` | Yes | Manual review |
| `manual` | Yes | Manual review |

Set `duplicate_of` and `parked_policy` when parking duplicates. No-diff parks from
`record-no-diff` are tagged automatically.

Workflow failure alerts only fire for **unresolved** failures (after the latest
successful run), scanned within a 12h window.

## Artifacts

| File | Purpose |
|------|---------|
| `docs/data/ops_status.json` | Latest findings, auto-fixes, workflow freshness |
| `docs/data/ops_monitor_log.json` | Rolling daily run index (90 entries) |
| `docs/data/backtest_health.json` | Backtest history audit and readiness (see [backtest-health.md](backtest-health.md)) |
| `docs/data/research_docs_receipt.json` | Sunday `--research-docs` claim receipt (writes / persist / mode counts) for L389 |

## Claimed-vs-landed integrity (L389)

Known-issue monitors can look green while the artifact that matters never moved.
`check_indicator_integrity` compares **claims** to **landings**:

| Check | Trigger | Severity |
|-------|---------|----------|
| `research_docs_claimed_zero_writes` | Fresh receipt: targets &gt; 0 but `created+updated=0` | fail |
| `research_docs_writes_not_persisted` | Fresh receipt: writes &gt; 0 but `persisted_trees=0` | fail |
| `research_docs_writes_without_structured_modes` | Fresh receipt: writes &gt; 0 but committed store still has 0 `structured_verdict*` modes | fail |
| `verdict_fields_without_structured_mode` | ≥5 committed memos have `research_verdict` while modes stay essay/`initial` and structured=0 | fail |

Receipts are written by `ftse-email --research-docs` (committed under
`docs/data/research_docs_receipt.json`; also under `output/`). Stale receipts
(&gt;10 days) are ignored. Complements `check_phase_b_producer_progress` (stall
detection) with false-green / claimed-vs-landed angles — see
[`structured-verdict-slim.md`](structured-verdict-slim.md).

## Paper learning tracks

The former weekday **Automation-tab spot-check** (CI acted; AI vs rules;
calibrated shadows; Suite B `buy_tier_level` fill) is a detection check, not a
human glance.

`check_paper_learning_tracks` reads committed `docs/data/paper_automation/`:

| Check | Severity | Notes |
|-------|----------|-------|
| `last_run.json` missing or `gate.after_settle=false` | warn | Orchestrator should re-dispatch a post-settle pass |
| `learning_tracks_summary.json` / `learning_tracks_review.json` missing, or missing `rules` / `ai_judgment` / `buy_tier_level` | fail | Weekday paper-auto + decision-review did not publish the comparison |
| Competing calibrated shadows present in the paper-auto rollup but omitted from decision-review | fail | Shadows spawned after the last paper-auto (Sunday calibrate) are ignored until they appear in the summary |
| `buy_tier_level` acted with empty `automated_fund.json` holdings | fail | Monday cold-start fill; do not treat NAV as promotion truth |
| Core track `acted=false` after a post-settle last_run | warn | Track skipped |

Does **not** alert on `beat_market` / excess vs ^FTSE. Underperformance on the
3% stress books is expected; interpretation stays Sunday analysis-review /
shadow-vs-primary / promotion gates.

Weekday paper findings before **10:00 UTC** defer alert email (same ready time
as `paper-auto.yml` workflow freshness). The 13:15 catch-up is the actionable
pass.

## CLI

```bash
# Check only (no writes beyond ops_status.json)
ftse-ops-monitor run --no-apply --no-draft

# Full run + email only when unfixed warn/fail remain after heal/re-verify
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
| **Library ladder** | Sunday | No success within 36h |
| **Library model review** | Sunday | No success within 36h |
| **Email report** | Sunday | No success within 36h |
| **Data backup** | Sunday | No success within 36h (12:30 UTC slot) |
| **Paper automation** | Weekdays | No success within 28h |
| **Ops monitor** | Daily | No success within 28h (self-check) |

Engineering queue reliability depends on external cron (`engineering-queue` job in
`import_cron_jobs.py`); GitHub `schedule` is backup only.

## Workflow failure recovery

When a Sunday bundle child fails on **main**, dedicated responders classify the
failed log and take a guarded next step (no blind infinite reruns).

| Responder | Trigger | Actions |
|-----------|---------|---------|
| **Library Ladder Responder** | `library-grow.yml` failure | Classify log → **one guarded rerun per ~20h** when partial success / transient / fixed corrupt-json; else draft engineering task |
| **Workflow Failure Responder** | `ingest-loop`, `email-report`, `analysis-review`, `library-model-review`, `data-backup`, `paper-auto`, `horizon-scan`, `automation-orchestrator` failures | Match log signature → draft scoped `workflow_failure` engineering task |
| **CI Fix Responder** | `CI` / `CI Main Nightly` pytest failures | Existing pytest-scoped auto-merge path |

Ledger: `docs/data/library/ladder_responder_log.json` records ladder reruns for
cooldown. Ops monitor surfaces **unresolved** `library-grow` failures on Sundays
via the workflow freshness table above.

CLI (local / Actions):

```bash
ftse-engineering respond-library-ladder --run-id <id>
ftse-engineering draft-workflow-failure --workflow-file ingest-loop.yml --run-id <id>
```

## Email policy

By default the workflow sends email only when **unfixed** findings leave overall
status `warn` or `fail` after heal/re-verify **and** those findings are not
deferred for later-day catch-up.

Auto-fixes, recovery-in-flight suppressions, and pre-slot Sunday overdue alone do
**not** send email — they still land in `ops_status.json` / `ops_monitor_log.json`.

Use workflow input `email_always=true` or `ftse-ops-monitor run --email-always`
for a digest regardless of status / deferral.

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
| Agent finished but spend commit to `main` raced | Retry `scripts/gha_commit_engineering_spend.sh`; do **not** treat as a task failure — PR open continues (`continue-on-error`) |
| Agent runs with **no committable code changes** | After **2** consecutive no-diff runs → `parked` (`record-no-diff` in `engineering-agent.yml`) |
| Agent runs with **no committable code changes** | After **2** consecutive no-diff runs → `parked` (`ftse-engineering record-no-diff`; wired in `engineering-agent.yml`) |

List parked tasks: `ftse-engineering list-parked`

### Engineering parked backlog clearing

When **8 or more** attention-parked engineering tasks accumulate, `engineering-queue`
pauses new **engineering-agent** dispatch and **parked-hunter-compile**, and sends a
full-queue email (ordered `list-parked` summary).

Human triage (oldest first):

1. `ftse-engineering list-parked`
2. For each task: merge the PR, cancel stale work, or unpark/reopen when appropriate
3. Duplicate/superseded hunter parks may auto-cancel during recovery — do not rely on
   mass auto-cancel; only obvious duplicates are trimmed automatically

**Auto-resume:** dispatch restarts when attention-parked count drops **below 7** **and**
**30 minutes** have elapsed since the last clearing action (cancel / merge / unpark).
Brief dips while you are still triaging therefore do not restart the queue mid-session.

Policy keys: `engineering.queue_recovery.max_attention_parked_tasks`,
`resume_attention_parked_below`, `resume_idle_minutes` in agent model policy.

### Project traffic controller (stuck PR pause)

When **2 or more** monitored `cursor/*` PRs are CI-red or merge-conflicting,
`ftse-project-traffic` (ops-monitor + weekday `project-traffic.yml`) sets
`traffic_control.pause_active` on `engineering_tasks.json`. That pauses
**engineering-agent** dispatch and **parked-hunter-compile** until stuck PRs clear
and a short idle window elapses.

The controller comments on stuck PRs and may dispatch
`engineering-conflict-resolve.yml` for `cursor/eng-*` branches. If the pause
stays active after first-line `ci-pr-autofix` / hunter-fix / conflict-resolve
had a chance to run, it dispatches **one** scoped unstick agent (`kind=escalation`).
That is an algorithmic trigger, not a standing GitHub→agent listener. It does
**not** merge. See [`project-traffic.md`](project-traffic.md).

### Hunter allowlist URL monitor

Hourly `recover-engineering-queue` re-live-fetches allowlist URLs from hunter tasks
merged in the last 30 days (default market: `euro_depth`). On failure:

1. Apply a known `_IR_ALLOWLIST_URL_CANONICAL` replacement in `filings.py` when the
   replacement URL still live-fetches cleanly
2. Else queue capped post-merge verify rework when the verify chain is not exhausted
3. Else draft a low-priority `hunter_url_repair` engineering task (deduped per ticker+URL)

Manual replay: `ftse-engineering monitor-hunter-urls --json [--dry-run]`

To resume a parked task manually, set status back to `open` in `engineering_tasks.json` or add a fresh task.

See also: [`orchestrator-cron.md`](orchestrator-cron.md), [`analysis-review.md`](analysis-review.md), [`backtest-health.md`](backtest-health.md), [`engineering-sync.md`](engineering-sync.md).
