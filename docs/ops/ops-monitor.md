# Ops monitor

Daily operational health checks for cron-driven workflows, committed
artifacts, ingest stall detection, and the engineering queue.

Ops monitor is the daily driver for **Lane A/B** intensive clearance (ingest stall
micro-compile, `so-what --apply`, engineering redispatch). Interpret post-run themes
via [`post-run-improvement-clearance.md`](post-run-improvement-clearance.md) — do not
treat Persistent weaknesses as N separate alert emails.

## Full automation wiring

**Any new component must be fully wired into automation so findings are usable** —
not shipped as CLI / manual-only. Applies to observe instruments, health checks,
utilization audits, and similar surfaces that produce actionable findings.

### Minimal bar (ship-blocking)

| Requirement | What “done” means |
|-------------|-------------------|
| **Scheduled trigger** | Invoked from daily ops-monitor `collect_ops_findings` (preferred) **or** a named workflow with cron / documented dispatch. No “remember to run the CLI.” |
| **Persisted finding** | When the condition fires, a finding lands in committed `docs/data/ops_status.json` (stable `title`, `severity`, `category`) via the ops-monitor artifact commit. |
| **Runbook mention** | Named in this doc (or a sibling instrument doc linked from here). |
| **CLI optional** | Manual `ftse-*` flags are for drill-down only — never the sole production path. |

### Observe vs auto-fixable lanes

| Lane | `auto_fixable` | Outcome when red |
|------|-----------------|------------------|
| **Observe / warn-only** | `False` | Finding + ops email / project-traffic PM handoff. Does **not** deepen ingest, rememo, or mint eng tasks from the finding alone. |
| **Auto-fixable** | `True` | Safe heal path in ops-monitor (or a documented supervised draft). Heal → re-verify before email. |

Do not promote an observe instrument into auto-fix / eng spray without an explicit
lane change and readiness gate (see N152 / P1 pin rules).

### Optional (not ship-blocking — park with `ftse-defer`)

- A dedicated workflow beyond the shared ops-monitor cron.

**Shipped above the bar:**

- **L461** — instrument-specific **Observe utilization** dashboard on Queue &
  hunter + Analysis (`docs/data/observe_utilization.json`), with freshness /
  staleness banners and trajectory deltas vs last cycle.
- **L460** — raw instrument stores (`buy_tier_flip_lag.json`,
  `decision_input_inventory.json`, `p1_first_run_pin.json`,
  `universe_filing_archive_miss_rate.json`) in
  ops-monitor `GHA_COMMIT_OPTIONAL` so
  daily cohort history persists in git (email-report excludes them so a broad
  `docs/data` overlay cannot rewind fresher ops commits).
- **L463** — **Lifecycle maturity mix trajectory** on Lifecycle → **Maturity mix**
  (`docs/data/lifecycle_maturity_trajectory.json`): per-market held-column
  shares / median age / UW-by-stage with freshness + Better/Worse history.
  Observe-only; **separated** from cumulative `beat_market`, exit_shadow,
  L462 WoW NAV, N153 FX, and decision-review. Ops finding only when the
  series is missing/stale (`auto_fixable=False`).
- **L468** — weekday **light** `lifecycle_board.json` refresh inside
  `check_lifecycle_maturity_trajectory` (via existing `write_lifecycle_board`,
  not a full email-report publish) so Maturity mix `surface_freshness` stays
  inside the ~30h content window between Sunday publishes. Board is in
  ops-monitor `GHA_COMMIT_OPTIONAL`; Pages deploys after a successful ops
  artifact push.
- **Human tasks board** — `docs/data/human_tasks_board.json` (+ durable
  `human_task_acks.json`) rebuilt at the end of each ops-monitor run from the
  checklist + existing analysis artifacts. Automation tab click-to-view cards
  sort new/changed analysis first; Acknowledge / Approve via dashboard-bridge
  (`human-task-ack`) are observe-only. Both JSON files are in
  `GHA_COMMIT_OPTIONAL`.
- **Daily hub + UI reconciliation** — `docs/data/daily_focus.json` (Cap C morning
  board), `docs/data/daily_hub_history.json` (History session), and
  `docs/data/ui_state_reconciliation.json` (Cap B dashboard health) rebuilt at
  end of ops-monitor after the human-tasks board — including the **02:30 UTC**
  early slot so the hub is fresh before 04:00 Europe/London. Automation →
  **Daily** (`#automation/daily`) is the collated cockpit (Today + History);
  **Ops** shows the reconcile table (includes `daily_hub_local_date_matches_today`).
  Findings titled **UI state reconciliation drift** are observe-only
  (`auto_fixable=False`). Accept / Discuss recommendations queue via
  `daily-focus-ack` / `daily-discuss` (inbox: `daily_discuss_inbox.json`).
  Accept-streak hints are observe-only — never auto-flip checklist `automated`.
  Morning board also emits **market warning triage** rows (deepen / dismiss /
  park) from open `market_status` admission flags and ingest deviations, plus
  **at most one** unmatched **workflow/CI failure** Daily-hub task
  (`gha:workflow-ci-failures`) with proposed solutions appended until acked
  for the local date (`docs/data/gha_failure_triage.json`; finding
  **GHA failure needs Daily-hub triage**, `auto_fixable=False`).
  Dispatch HTTP 403 / missing `actions: write` is allowlisted (hygiene scan +
  supervised YAML task) and does **not** mint a hub rec.
- **Missing-IR allowlist stall** — ops finding when focus **or spare sprint**
  `unmeasured_stuck` / `zero_body_stuck` tickers still have empty IR allowlist
  after ≥2 intensive 0-improve pins (`check_missing_ir_allowlist_stall`,
  `auto_fixable=False`; severity `high` on focus head, `warn` on spare —
  e.g. DAX `G1A.DE`). Complements Daily deepen Discuss; aims at IR seed,
  does not auto-park unmeasured. Gap-closure eng compile also prioritizes
  coverage-hole + empty-allowlist pending runs over stale IWB rows.

Also pinned in root [`AGENTS.md`](../../AGENTS.md#full-automation-wiring-required).

**Heal → re-verify → report** (when `--apply` / default in CI):

1. Detect findings (artifacts, ingest health, workflows, engineering queue, Phase B
   structured-verdict producer progress, claimed-vs-landed indicator integrity
   (**L389**), …)
2. Apply **safe auto-fixes** (below)
3. **Re-run detection** so overall status reflects post-fix truth
4. Draft supervised tasks / send email only for **unfixed** warn/fail
5. On email send: hand the same findings to project-traffic PM with the email body
   and a planned rectification (auto-fix only within PM v1; see
   [project-traffic.md](project-traffic.md#ops-monitor-email-handoff-l397))

**Safe auto-fixes:**

- Reconcile orphaned `pr_open` engineering tasks (no matching open PR)
- Restamp `open` → `pr_open` when a live engineering PR already exists (stamp lag after orphan-reconcile races; unblocks scoped auto-merge)
- Normalize corrupt `ingest_health_log.json` (with sibling backup)
- Micro-compile ingest engineering tasks when buy-tier filing ingest is stalled
- **Thin-memo factory heal** when `thin_memo_counted_as_coverage` is open: deepen
  zero-body focus library memos, body-lag rememo pending names (when Cursor API
  key present), refresh `system_gaps.json` — same Lane A path as euro-ingest-loop
  (see [so-what-gap-closure.md](so-what-gap-closure.md#thin_memo_counted_as_coverage))
- Market-rotating library eng gap burn-down when the ingest eng slot is free ([`market-eng-gap-burndown.md`](market-eng-gap-burndown.md))
- Grade parked engineering tasks and auto-cancel duplicates of merged work
- Quarantine corrupt or duplicate backtest history snapshots (see [backtest-health.md](backtest-health.md))
- Reconcile engineering queue sync issues and redispatch when the agent failed on a stale task id (see [engineering-sync.md](engineering-sync.md))
- Detect **queue merge-sync lag** (`pr_open`/`open` after GitHub merge) and hand it to the project-traffic PM controller; **email only if PM remediation cannot clear it**
- Detect **automation waste** (engineering-agent Composer reburn; Cursor workflow fail loops) and hand remediable signals to project-traffic (`stop_automation_waste` parks + pause)
- Suppress “recent workflow failure” alerts while a recovery run for that workflow is already in flight
- Suppress workflow-overdue findings while a run is in flight, or before that workflow’s `WORKFLOW_EMAIL_READY_UTC` slot (Monday morning cliff / pending primary cron). Freshness itself is schedule-aware: `stale` is false until that wall-clock slot, so Sunday weekly jobs (~7d since last success) and weekday post-weekend ages do not create overdue rows or STALE colours before the first expected fire
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
| **cron-job.org (primary)** | Daily **02:30 UTC** early hub (`30 2 * * *`) + **07:45 UTC** morning (`45 7 * * *`) + **13:15 UTC** catch-up (`15 13 * * *`) |
| GitHub cron (backup) | Same expressions |
| Manual | Actions → **FTSE Ops Monitor** → Run workflow |

**Early slot (Daily hub Phase A0):** `02:30 UTC` always lands **before 04:00 Europe/London**
year-round (02:30 GMT / 03:30 BST). Rebuilds `daily_focus.json` + `daily_hub_history.json`.
The skip-if-finalized gate **ignores successes before 06:00 UTC**, so the 07:45 morning
detect/heal still runs after the early hub refresh.

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
logs overlay only when `main` has not changed them since checkout. Email-report
owns broad `docs/data` for dashboard publish but sets `GHA_COMMIT_EXCLUDE` for
`ops_status.json` / `ops_monitor_log.json` / progress-report artifacts
(`progress_report.json` / `.md` / `project_progress.json`) so a long screen run
cannot rewrite a fresher ops-monitor or progress-report commit from its checkout
snapshot. Shared `gha_commit_artifacts.sh` also skips owned `*.json` overlay when
`origin/<ref>` already has a newer top-level `generated_at` (defense in depth for
foreign-owned dashboard JSON). The workflow commits those
artifacts even when `ftse-ops-monitor` exits non-zero, then fails the job afterward
so a red finding cannot leave `ops_status.json` stale.

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

### cron-job.org setup (one-time) {#cron-joborg-setup-one-time}

Register **three** HTTP jobs on cron-job.org (early hub + morning + catch-up).
This is separate from the GitHub `workflow_dispatch` curl above — cron-job.org
calls GitHub on your behalf. Prefer the import script (idempotent by title):

```bash
export CRONJOB_API_KEY=…   # cron-job.org → Settings → API
export WORKFLOW_DISPATCH_PAT=…            # fine-grained PAT, Actions: Read and write on this repo

CRONJOB_API_KEY=… WORKFLOW_DISPATCH_PAT=… ./scripts/import_cron_jobs.py \
  --job ops-monitor-early --job ops-monitor --job ops-monitor-catchup
```

| Job key | Title | UTC schedule | Role |
|---------|-------|--------------|------|
| `ops-monitor-early` | FTSE ops monitor early hub (daily) | `30 2 * * *` | Daily hub before **04:00 Europe/London** |
| `ops-monitor` | FTSE ops monitor (daily) | `45 7 * * *` | Morning detect / heal |
| `ops-monitor-catchup` | FTSE ops monitor catch-up | `15 13 * * *` | Day-complete email if still red |

`ops-monitor-early` is in `KNOWN_JOB_IDS` (jobId `8550657` as of 2026-10-01).
Re-import only if deleted. GitHub `schedule` expressions are backup only.

Dry-run payloads: `./scripts/import_cron_jobs.py --job ops-monitor-early --dry-run --json`

**curl (morning job example):**

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

For the early hub job, use title `FTSE ops monitor early hub (daily)` and
`hours: [2], minutes: [30]` (same URL/body). Or import with `--job ops-monitor-early`.

Verify:

```bash
gh run list --workflow=ops-monitor.yml --limit 5
```

Expect a successful `workflow_dispatch` near **02:30 UTC** (hub date rolls) and
again near **07:45 UTC**; `docs/data/ops_status.json` / `daily_focus.json` update
each full monitor pass.

See [orchestrator-cron.md](orchestrator-cron.md) for the repo-wide scheduling policy.

### Parked engineering tasks

The daily ops monitor **grades** parked tasks (no separate housekeeping loop):

| `parked_policy` | Ops email alert? | Auto action |
|-----------------|------------------|-------------|
| `duplicate` (of merged task) | No | Cancel task when `duplicate_of` is merged |
| `no_diff_cap` | No | Annotate policy only |
| `preflight_clash` | Yes | Manual review (agent park committed to main) |
| `reburn_loop` | Yes | Traffic PM parked after Composer reburn; triage before unpark |
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
| `learning_tracks_summary.json` / `learning_tracks_review.json` missing, or missing the assessment-model primary / control / `buy_tier_level` | fail | Weekday paper-auto + decision-review did not publish the comparison. Core ids come from `paper_automation/assessment_model.json` (legacy roots: `ai_judgment` / `rules`) — see [`primary-learning-track.md`](primary-learning-track.md#assessment-model-and-frozen-tracks) |
| Competing calibrated shadows present in the paper-auto rollup but omitted from decision-review | fail | Shadows spawned after the last paper-auto (Sunday calibrate) are ignored until they appear in the summary; frozen shadows are skipped |
| `buy_tier_level` acted with empty `automated_fund.json` holdings | fail | Monday cold-start fill; do not treat NAV as promotion truth |
| Core track `acted=false` after a post-settle last_run | warn | Track skipped |
| `learning_tracks_llm_agree_veto.json` missing after core tracks acted | warn | Observe-only algo→agree/veto shadow; never blocks fills — see [`llm-agree-veto-shadow.md`](llm-agree-veto-shadow.md) |
| Any tunable review row (not frozen, not a fixed-knob lab) with non-empty `saturated_knobs` | warn | **Decision-review knobs saturated at bounds** — a proposal rule still fires but the knob is at its clamp bound, so the loop can no longer respond on that axis. `auto_fixable=False`; human decides whether the driver (cost model, churn, concentration) needs a policy change or new epoch — see [`decision-review.md`](decision-review.md#apply-gate-and-cooldown) |

Graduation → observe refinement children (lineage on experiment assessment) are
documented in [`refinement-learning-loops.md`](refinement-learning-loops.md);
they do not emit a separate ops finding (fail-closed / observe-only marks).

Does **not** alert on `beat_market` / excess vs ^FTSE. Underperformance on the
3% stress books is expected; interpretation stays Sunday analysis-review /
`paper_track_buckets` (Suite A drag, Suite B fair excess, identity floor — not
one NAV line). See [`analysis-review.md`](analysis-review.md#dual-suite-paper-track-buckets-legacy-context).

LLM live-path evidence principle (any LLM influence requires durable trail
evidence; shadow first): [`llm-live-path-evidence.md`](llm-live-path-evidence.md).
Shadow cards are written on each paper-auto pass into the rebalance log and
per-track `llm_agree_veto_shadow.json` — see
[`llm-agree-veto-shadow.md`](llm-agree-veto-shadow.md). Weekday overlay refresh
(`refresh_dashboard_bundle`) round-trips filing presence, FCF overlay, overlay
bind, and EPS-from-body onto reports → slim candidates → agree/veto cites
(observe-only; does not enable Phase C `autopsy_freeze`). First-run observe pin:
`check_p1_first_run_pin` (time-boxed; see table below).

Weekday paper findings before **10:00 UTC** defer alert email (same ready time
as `paper-auto.yml` workflow freshness). The 13:15 catch-up is the actionable
pass.

## Observe utilization instruments (P1)

Both checks are **observe / warn-only** (`auto_fixable=False`). They refresh a
runner-local store JSON and emit an ops finding when the warn cohort is material.
Manual drill-down: `ftse-ingest-audit --flip-lag` /
`ftse-ingest-audit --decision-inputs` /
`ftse-ingest-audit --archive-miss-rate` /
`ftse-ingest-audit --p1-first-run` (mutually exclusive) /
`ftse-universe-archive-pack` (archive pack gate + bottleneck summary).
They do **not** deepen ingest or rememo.

| Check | Finding title | When it warns | Store (runner) | Status |
|-------|---------------|---------------|----------------|--------|
| `check_buy_tier_flip_lag` | **New buy-tier not yet usable** | Path-incomplete ≥24h cohort non-empty (FTSE live ∪ admitted; schema v2). Library rows treat a sibling `research_home_market` as `has_memo` (observe-only; no auto-fix, no memo copy). FTSE live stays on `docs/data/research`. | `docs/data/buy_tier_flip_lag.json` | Live on main |
| `check_decision_input_inventory` | **FTSE decision-input utilization gap** | Dominant bind gap count ≥3 on FTSE holdings ∪ buy-tier (else quiet / `P1 green-enough`) | `docs/data/decision_input_inventory.json` | Live on main |
| `check_p1_first_run_pin` | **P1 first-run: EPS-from-body missing after Sunday screen** / **… slim freeze missing after Monday paper-auto** | After the relevant post-#953 run, EPS-from-body still 0/n on holdings ∪ buy-tier reports or `rebalance_log` slim. Auto-oks when a count lands. Empty/pre-Sunday is **not** a warn. Window 10d from #953 merge then expires (no forever babysit). Not a soak platform or utilization dashboard | `docs/data/p1_first_run_pin.json` | First-run pin |
| `check_universe_filing_archive_miss_rate` | **Universe archive body-miss rate elevated** | Flip-lag proxy miss rate elevated with open body gaps — observe-only outcome (not a cold-store start gate; N180/N181) | `docs/data/universe_filing_archive_miss_rate.json` | Scaffold live |
| `check_universe_filing_archive_pack_bottleneck` | **Universe archive pack bottleneck review stale** / **… processing bottleneck** | Bottleneck review missing/stale (>36h) or dominant stage / errors on an allowed dry pass; suspend/quiet_only while euro fat does **not** warn | `docs/data/universe_filing_archive_bottleneck_review.json` (owned by `universe-filing-archive-pack.yml` @ 22:00 UTC weekdays) | Gated dry lane live |

Thin **L521** Ops panel: `docs/data/universe_filing_archive_status.json` (last outcome,
dry/apply, clash/`capacity_isolation` flags, next widen step). Written by the
archive pack workflow and refreshed at end of ops-monitor. Dashboard: Automation → Ops.
| `check_shard_nav_fx_warp` | **Shard NAV FX unit mismatch** | Non-GBP shard GBP book shows day-0 NAV≈FX and `buy_tier_level_native` is not yet active (N153) | `docs/data/shard_nav_fx_warp.json` | Live with N153 |
| `check_screen_premise_backtest` | **Value screen buy tier trails screened universe** | Frozen-signal backtest over weekly run snapshots: the buy/strong_buy minus screened-universe forward-return spread has a 90% interval wholly below zero at 7d or 28d. Intervals are withheld until the overlap-adjusted sample reaches 4. Observe-only (L530) — see [screen-premise-backtest.md](screen-premise-backtest.md) | `docs/data/screen_premise_backtest.json` | Live |
| `check_value_factor_base_rate` | **Value factor base rate missing** / **… is stale** | The committed Ken French summary is missing or its US data cut is older than 18 months. A small premium is not a finding. Observe-only — see [value-factor-base-rate.md](value-factor-base-rate.md) | `docs/data/value_factor_base_rate.json` | Live |
| `check_unsettled_corporate_actions` | **Paper holding has an unsettled terminal event** | A cash bid or delisting on a paper book has no cash amount, so the position is left open. Splits and cash amounts are applied before rebalance from the corporate-actions feed. Observe-only — see [corporate-actions.md](corporate-actions.md) | track `automated_fund.json` | Live |
| `check_investor_yield` | **Non-UK library screen has no investor net yield** | A non-UK `latest_signals.csv` has no `investor_net_yield_isa` column, so a later total-return judgement would still be looking at gross yield. The next library screen writes it. Live FTSE signals stay on gross yield. Observe-only — see [investor-yield.md](investor-yield.md) | library `latest_signals.csv` | Live |
| `check_paper_halt` | **Paper book would halt on drawdown or concentration** | Peak-to-trough drawdown, single-name weight, sector weight, or currency concentration crossed the observe thresholds. The book is not frozen. Observe-only — see [paper-halt.md](paper-halt.md) | `docs/data/paper_halt.json` | Live |
| `check_combined_tagged_learning` | **Combined tagged learning store stale** | Observe store missing/stale. Zero closed N is **not** a warn. Tagged join only — no NAV blend / knob apply (N23) | `docs/data/combined_tagged_learning.json` | Live scaffold |
| `check_track_statistics` | **Learning-track verdict not statistically supported** | `learning_tracks_review` claims `beat_market` (AI vs benchmark) or `beat_control` (AI minus rules) but the 90% bootstrap CI does not show a positive edge. Tracks merely being noisy is **not** a warn. Observe-only (L529) — see [`track-statistics.md`](track-statistics.md) | `docs/data/track_statistics.json` | Live on main |
| `check_decision_review_significance_gate` | **Decision-review significance gate starved of statistics** | A track in `learning_tracks_review.json` had its knob apply blocked because `track_statistics.json` was missing, unreadable, older than 4 days or on another benchmark, **and** the store is still unusable at check time (the next paper-auto would be starved too). A gate closed on evidence (noise, <20 periods) is the policy working, not a finding. Observe-only — see [`decision-review.md`](decision-review.md#significance-gate-significance_gate_v1) | `docs/data/paper_automation/learning_tracks_review.json`, `docs/data/track_statistics.json` | Live on main |
| `check_total_return_view` | **Price-only excess misstates track performance** | Published excess vs `^FTSE` and total-return excess vs `FTAL.L` (dividends credited; clean epoch for fair-cost books) differ by sign or ≥5pp on a headline track. Observe-only — no metric/knob rewrite. See [total-return-view.md](total-return-view.md) | `docs/data/total_return_view.json` | Live |
| `check_assessment_scoreboard` | **Primary book trails its control on total return** | Single fair-cost scoreboard (total return vs `FTAL.L`, 90% CI, 3% stress-cost sensitivity, gate binding). Warns when the assessment-model primary is ≥5pp behind its control on the common window. Observe-only — see [assessment-scoreboard.md](assessment-scoreboard.md) | `docs/data/assessment_scoreboard.json` | Live |
| `check_deferred_triggers` | **Deferred idea triggers met** / **… unreadable** / **… name frozen books** | An open deferred idea's structured `trigger` is met; a trigger is invalid or unknown for more than 7 days; or a free-text `revisit_when` still names a book frozen after the idea was last edited. Warn-only; a human picks up, retargets or closes the idea. See [deferred-triggers.md](deferred-triggers.md) | `docs/data/deferred_trigger_check.json` | Live |
| `check_hold_period_counterfactual` | **Longer holds beat live exit buffer in replay** | A faithful replay of logged passes (baseline within 1% of logged NAV) with `exit_confirm_screens` 5/10/20 beats the live knob by ≥1pp on a headline track. Observe-only (L531) — no knob edit; next step is a cold-start twin. See [hold-period-counterfactual.md](hold-period-counterfactual.md) | `docs/data/hold_period_counterfactual.json` | Live |
| `check_sec_companyfacts_coverage` | **SEC filed FCF diverges from Yahoo basis on US buy-tier** / **SEC companyfacts coverage below target on US memos** | Divergence: SEC-filed OCF − capex differs from the Yahoo `filing_aligned` basis by >25% on a US buy-tier memo name (`info` for 1–2 names, `warn` from 3). Coverage: under 80% of US memo names have `sources/sec_companyfacts.json` (`info`). Observe-only (L544) — scoring still reads Yahoo. See [sec-companyfacts.md](sec-companyfacts.md) | `docs/data/sec_companyfacts_coverage.json` | Live |
| `check_hkex_direct_coverage` | **HKEX direct filings not yet on hang_seng buy-tier memos** / **HKEX direct feed silent on freshly ingested hang_seng memos** | Coverage: under 80% of hang_seng buy-tier names have `hkex_direct` annual + interim bodies (`info`). Silent: a `.HK` index fully re-ingested in the last 7 days has zero `hkex_direct` rows (`info` for 1, `warn` from 2), meaning HKEXnews changed shape. Observe-only (L543); reads committed indexes. See [hkex-direct-filings.md](hkex-direct-filings.md) | `docs/data/hkex_direct_coverage.json` | Live |
| `check_amf_direct_coverage` | **AMF direct filings not yet on French buy-tier memos** / **AMF direct feed silent on freshly ingested French memos** | Coverage: under 80% of French buy-tier names (`.PA` / French LEI across euro markets) have `amf_direct` annual + interim bodies (`info`). Silent: a French index fully re-ingested in the last 7 days has zero `amf_direct` rows (`info` for 1, `warn` from 2), meaning the AMF open-data dataset changed. Observe-only (L545); reads committed indexes. See [amf-direct-filings.md](amf-direct-filings.md) | `docs/data/amf_direct_coverage.json` | Live |
| `check_cision_direct_coverage` | **Cision direct filings not yet on Swedish buy-tier memos** / **Cision direct feed silent on freshly ingested Swedish memos** | Coverage: under 80% of mapped Swedish buy-tier names (`CISION_NEWSROOMS`, omxs30 + euro_depth) have `cision_direct` annual + interim bodies (`info`). Silent: a mapped Swedish index fully re-ingested in the last 7 days has zero `cision_direct` rows (`info` for 1, `warn` from 2), meaning a newsroom slug changed or the issuer left Cision. Observe-only (L556); reads committed indexes. See [cision-direct-filings.md](cision-direct-filings.md) | `docs/data/cision_direct_coverage.json` | Live |

Isolation firewall + fail-open hydrate + **week-first gated dry pack** (no crawler): see
[`universe-filing-archive-pack.md`](universe-filing-archive-pack.md).
Manual drill-down: `ftse-universe-archive-pack` (fail-open suspend under focus fat).

Called from `collect_ops_findings` on the daily ops-monitor schedule. Raw
instrument store JSON **is** in `GHA_COMMIT_OPTIONAL` (**L460**) so day-over-day
cohort history lands in git with ops-monitor. The **instrument dashboard**
rollup `docs/data/observe_utilization.json` is also committed with queue-health
refresh (ops-monitor / dashboard-bridge): Queue & hunter + Analysis show warn
state, **freshness / staleness**, and **trajectory** (delta vs last cycle;
lower warn/gap = better). Prefer those trajectory indicators over
non-contextual absolute counts. A `lagging` freshness badge now means a
commit-path anomaly (stores should co-commit with `ops_status`); it is no
longer an intentional gap. Archive pack run / bottleneck / status-panel JSON are
owned by the archive workflow (not L460) so ops-monitor cannot rewind a fresher
pack pass; ops-monitor still refreshes `universe_filing_archive_status.json`
hours-since / next-widen from the committed pack_run.

## Lifecycle maturity mix trajectory (L463)

Observe-only composition twin for open books. Spot mix already lives on
`lifecycle_board`; this instrument appends a slim **history** of:

| Metric | Definition |
|--------|------------|
| Early share | `(just_bought + growth) / held` on `buy_tier_level` (else default track) |
| Median age | Median `days_in_column` on held columns (shown cards; truncated flagged) |
| UW-by-stage | Share of shown cards with `unrealized_pnl_pct < 0` per held column |

FTSE live reports may omit `last_price`; board enrich (L464) fills marks from
library signals / HI price map so UW is not blank. Still local P&L vs
`avg_cost` — not FX.

**Separation (hard):** does not feed or rewrite cumulative / epoch
`beat_market` / `excess_after_costs`, exit_shadow / realized-at-exit reviews,
L462 WoW NAV twin, N153 FX bookkeeping, or decision-review knob apply.
| Surface | Detail |
|---------|--------|
| Store | `docs/data/lifecycle_maturity_trajectory.json` (ops-monitor optional commit + dashboard-bridge; email-report excludes) |
| Board | `docs/data/lifecycle_board.json` — light weekday refresh (**L468**) before maturity collect when age ≥18h; also email-report / local `/api/refresh` / lifecycle experiment start\|ack |
| Trigger | `collect_ops_findings` → `check_lifecycle_maturity_trajectory` (board light-refresh then twin); also queue-health |
| Dashboard | Lifecycle → **Maturity mix** (`#lifecycle/maturity`) — trajectory badges + freshness (prefer over raw counts); Positions board stays on `#lifecycle` / `#lifecycle/{market}` |
| Finding | **Lifecycle maturity mix trajectory stalled** when missing/stale (`auto_fixable=False`) |
| CLI (optional) | `ftse-dashboard-bridge refresh-lifecycle-maturity`; `ftse-dashboard-bridge refresh-lifecycle-board` |

Young / focus books looking early-heavy is expected — headline context, not a heal cue.

### Weekday light lifecycle_board refresh (L468)

Maturity mix `surface_freshness` follows **board content age**
(`lifecycle_board.generated_at`), not the maturity twin store age. Before L468,
ops-monitor refreshed only the twin, so mid-week gaps after a sparse
email-report correctly showed **Surface stale** until the next Sunday publish.

| Layer | Behavior |
|-------|----------|
| Helper | `maybe_refresh_lifecycle_board` → existing `write_lifecycle_board` (all admitted markets / board surfaces; no screen rewrite) |
| When | Board missing/unreadable **or** age ≥ `DEFAULT_BOARD_LIGHT_REFRESH_AFTER_HOURS` (18h, under the 30h stale banner) |
| Trigger | Daily ops-monitor `collect_ops_findings` → `check_lifecycle_maturity_trajectory` |
| Commit | `docs/data/lifecycle_board.json` in `GHA_COMMIT_OPTIONAL` (race-safe with email-report / experiment workflows) |
| Pages | `ops-monitor.yml` dispatches `pages.yml` after a successful artifact push so the live dashboard clears the banner |

Still does **not** contaminate `beat_market` or other analysis measures — board
rebuild is observe composition only.

## UI state reconciliation {#ui-state-reconciliation}

Observe-only **dashboard health** instrument (Cap B). Compares named UI artifacts
so operators can tell when Pages is lying about the working set automation used.

| Layer | Behavior |
|-------|----------|
| Store | `docs/data/ui_state_reconciliation.json` (ops-monitor optional commit; email-report excludes) |
| Trigger | `collect_ops_findings` → `check_ui_state_reconciliation`; refreshed again after human-tasks board write |
| Checks (v0) | Progress report present; dual-suite scoreboard present; human-task ack FP mass-stale heuristic; lifecycle board age ≤ ~30h |
| Dashboard | Overview pulse strip + Automation → **Ops** (`#automation/ops`) full table; Daily hub badge |
| Finding | **UI state reconciliation drift** when `overall` is warn/fail (`auto_fixable=False`, category `dashboard_health`) |
| Non-goals | No eng spray, no auto-republish, no primary-track flip |

Policy green ≠ utility: a Suite A stress book being “primary” does not clear reconcile ambers.

## Daily hub {#daily-hub}

Morning cockpit (Cap C). Operator TZ **Europe/London**; hub payload for “today”
should be ready **before 04:00** local via the **02:30 UTC** early ops-monitor slot
(not by redefining fresh as ~08:45). Built from Project focus seed
(`project_daily_seed.json` / notes Today bullets), **market warning triage**
(open `market_status` admission flags + open ingest deviations → deepen /
dismiss / park), human-tasks open buckets, progress `defer_now`, and reconcile
ambers. History session lists completed **development** tasks (`work_class=dev`)
with **Accept followed** vs **Discuss resolved**.

| Layer | Behavior |
|-------|----------|
| Store | `docs/data/daily_focus.json` (+ `daily_focus_acks.json`, `daily_discuss_inbox.json`, `daily_hub_history.json`, `project_daily_seed.json`, `gha_failure_triage.json`) |
| Trigger | End of `run_ops_monitor` (after human-tasks board); early **02:30 UTC** + morning **07:45 UTC**; optional commit via `GHA_COMMIT_OPTIONAL` |
| Stale | Builder `stale_for_local_date` + client wall-clock (`Europe/London` date ≠ artifact `local_date`) amber banner; reconcile check `daily_hub_local_date_matches_today` after 04:00 |
| Dashboard | Automation → **Daily** (`#automation/daily`): **Today** session + **History** session; Overview pulse embeds top focus lines + history counts |
| Close | Focus lines → `daily-focus-ack` (enriched title/work_class/outcome); human tasks → existing `human-task-ack`; **UI reconcile** ambers → `daily-focus-ack` with `decision=dismiss` (observe-only for `local_date`; Accept is not link-only) |
| Recommendations | Per-task `recommendation` with **Accept** / **Discuss**; structured `options[]` (`{id,label,action}`) render as in-card buttons (human-task ack/defer/approve, focus-ack park, runbook links) without Project chat; Discuss writes `daily_discuss_inbox.json` and copies a Project pickup prompt |
| Review detail | Human-task cards embed `review_detail` (analysis headline + bullets + runbook link) beside the assessment paragraph so PR-fix / checklist review context stays on-card |
| Cap B before Cap C | `write_daily_focus` refreshes `ui_state_reconciliation.json` before embedding reconcile rows so hub-only rebuilds (ack / discuss / human-task-ack) cannot stick a cleared amber |
| Client heal | If `reconcile:daily_hub_local_date_matches_today` is still open but hub `local_date` already equals Europe/London today, Daily UI auto-closes the card (covers Pages lag after Cap B cleared on main) |
| Discuss auto-resolve | When Cap B / hub no longer opens a reconcile check, `write_daily_focus` resolves matching open `daily_discuss_inbox` rows (Discuss alone never closes) |
| Pages deploy | `pages.yml` uses `cancel-in-progress: true` so a stuck environment wait cannot block newer deploys; daily-focus-ack / daily-discuss dispatch `pages.yml` after `[skip ci]` commits |
| Market warning triage | Open admission flags (`zero_body_stuck`, `unmeasured_stuck`, `zero_improve_stall`, …) + open ingest deviations become Daily rows with structured `triage_action` ∈ {`deepen`,`dismiss`,`park`}. **Accept** = observe-safe `focus-ack` when park/dismiss is safe; **Discuss** preferred for fat-slot / rate-limit deepen (euro head). `zero_body_stuck` / `unmeasured_stuck` are **not** dismissable or parkable. When those stuck tickers also have **empty IR allowlist**, triage rationale names IR-seed (deepen alone 0-yields) — still not auto-park. Do not ritual-clear bare `health=warn`. Spare DAX stall → park (do not divert euro). Ingest-deviation dismiss CLI stays manual (Phase B automation parked). |
| GHA failure bundle | Unmatched workflow/CI failures (not on the ci-fix allowlist, not known flakes, not skip_draft timeouts) append onto **one** Daily-hub task (`gha:workflow-ci-failures`) for the Europe/London local date until Accept/ack. Distinct failure types + proposed solutions stack in `docs/data/gha_failure_triage.json`. One discuss rec for the window. Dispatch 403 / missing `actions: write` is hygiene + supervised YAML (email-report pattern), not this card. Ops finding **GHA failure needs Daily-hub triage** (`auto_fixable=False`). |
| Status chips | `ready` / `next_steps` / `waiting_on` from seed + notes `Next:` / `Waiting on:` conventions |
| Expansive assessment | Per-task structured `assessment` fields (`where_we_are`, stage duration / `stage_since`, `waiting_for`, `how_achieved`) from seed, notes (`Where:` / `Stage:` / `Since:` / `How:`), status markers, and observe fillers (market triage, human gates, reconcile). Missing duration stays `duration unknown` in JSON (no invented dates). **UI** renders one coherent paragraph from the fields that are present — empty waiting/how and bare “proposed / duration unknown” are omitted (no labeled “not stated” rows) |
| Accept-streak hint | Observe-only footer when ≥5 Accepts / 30d with 0 Discuss on a family — never auto-flips `automated: true` (N169) |
| Aim filter | Suite A stress streaks / off-buy-tier zero-filing themes stay out unless already a checklist item or focus line |

Project notes `Today —` bullets are the editorial surface; after the morning build,
JSON wins for the UI. Agents do not push unprompted into chat — say
`discuss daily recommendation \`rec-…\`` in the Project conversation.

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
| Analysis review | Sunday | After email-ready **11:00 UTC**, no success within 36h (primary ~10:35) |
| **Library ladder** | Sunday | After email-ready **08:00 UTC**, no success within 36h |
| **Library model review** | Sunday | After email-ready **08:00 UTC**, no success within 36h |
| **Email report** | Sunday | After email-ready **09:00 UTC**, no success within 36h |
| **Data backup** | Sunday | After email-ready **13:00 UTC**, no success within 36h (primary ~12:30) |
| **Paper automation** | Weekdays | No success within 28h |
| **Ops monitor** | Daily | No success within 28h (self-check) |
| **Dashboard bridge** | Weekdays | No success within **1h** (external every-10m primary; see [`dashboard-bridge.md`](dashboard-bridge.md#schedule-primary-vs-backup)) |

Engineering queue reliability depends on external cron (`engineering-queue` job in
`import_cron_jobs.py`); GitHub `schedule` is backup only. Dashboard bridge uses the
same pattern (`dashboard-bridge` job — weekday every 10 minutes).

## Workflow failure recovery

When a Sunday bundle child fails on **main**, dedicated responders classify the
failed log and take a guarded next step (no blind infinite reruns).

| Responder | Trigger | Actions |
|-----------|---------|---------|
| **Library Ladder Responder** | `library-grow.yml` failure | Classify log → **one guarded rerun per ~20h** when partial success / transient / fixed corrupt-json; else draft engineering task |
| **Workflow Failure Responder** | `ingest-loop`, `euro-ingest-loop`, `library-ingest-sprint` / `-2`, `library-ingest-maintenance`, `email-report`, `analysis-review`, `library-model-review`, `data-backup`, `paper-auto`, `horizon-scan`, `automation-orchestrator` failures | Match log signature → draft scoped `workflow_failure` engineering task |
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
| `open`/`pr_open` whose eng PR already merged | Stamp → `merged` (REST `head=` + `pr_number` + `gh` fallback; also re-healed immediately before dispatch and inside `queue-status`) |
| `preflight_clash` / `workflow_permission` with filings/CH/OCR title but ops/workflow allowlist | Cancel → `cancelled` (`mis_scoped_allowlist` housekeep) |

List parked tasks: `ftse-engineering list-parked`

### Engineering parked backlog clearing

When **8 or more** attention-parked engineering tasks accumulate, `engineering-queue`
pauses new **engineering-agent** dispatch and **parked-hunter-compile**, and sends a
full-queue email (ordered `list-parked` summary).

**Tier-1 auto housekeep** (hourly `recover-queue`, policy
`engineering.queue_recovery`) runs **before** the pause / warning-email evaluation so
self-heal can avert the alert when possible:

| Auto action | When |
|-------------|------|
| Cancel `duplicate_of` merged | Explicit duplicate parks |
| Cancel superseded parked hunters | Ticker already on `main` |
| Cancel mis-scoped allowlist parks | Filings/CH/OCR title + ops/workflow allowlist |
| Cancel `no_diff_cap` parks | When at the attention cap (`auto_cancel_no_diff_cap=at_cap`) |
| Cancel resolved gap-closure parks | Ticker no longer has outstanding *material* gaps |
| Cancel superseded gap-closure parks | Same-ticker sibling already merged |
| Unpark healed `preflight_clash` | Clash checks clean against current in-flight work |
| Library stall triage | `recover_engineering_queue` tier-1 housekeep: supersede/resolve cancel, `stall_triage` annotate, optional reburn narrow-reframe, **auto-unpark** cleared `reburn_loop` stalls when dispatch gates allow (`library_stall_task_triage`) |

Remaining `ci_blocked` / stubborn `preflight_clash` / manual parks still need human triage.

**Quiet observe auto-ack:** when `attention_parked_count=0` and
`queue_clearing.pause_active=false` (after recover-queue), the checklist card
`weekday-engineering-parked-backlog-clear` is **auto_ackable** — board rebuild
records observe-only `ack_observe` (`source=board_auto_quiet_parked_backlog`).
That refreshes the Daily hub fingerprint without `list-parked` work. It does
**not** unpark, cancel, or resume dispatch. Human triage stays required when the
cap-8 pause / warning still fires after self-heal.

Human triage (oldest first) for parks that survive self-heal:

1. `ftse-engineering list-parked`
2. For each task: merge the PR, `ftse-engineering cancel-task --task-id … --reason …` for stale/superseded work, or `ftse-engineering unpark-task --task-id … --reason …` when appropriate
3. Tier-1 trims resolved/superseded/healed parks automatically — do not re-triage those

**Auto-resume:** dispatch restarts when attention-parked count drops **below 7** **and**
**30 minutes** have elapsed since the last clearing action (cancel / merge / unpark).
Brief dips while you are still triaging therefore do not restart the queue mid-session.

Policy keys: `engineering.queue_recovery.max_attention_parked_tasks`,
`resume_attention_parked_below`, `resume_idle_minutes`, plus the
`auto_cancel_*` / `auto_unpark_healed_preflight` / `auto_unpark_cleared_reburn_library_stall`
flags in agent model policy.

### Project traffic controller (stuck PR pause)

When **2 or more** monitored `cursor/*` PRs are CI-red or merge-conflicting,
`ftse-project-traffic` (ops-monitor + weekday `project-traffic.yml`) sets
`traffic_control.pause_active` on `engineering_tasks.json`. That pauses
**engineering-agent** dispatch and **parked-hunter-compile** until stuck PRs clear
and a short idle window elapses.

The same controller also stops **automation waste**: when engineering-agent fails
repeatedly on the same open task with no in-flight PR (Composer reburn), traffic
parks the task (`reburn_loop`) and holds dispatch until the waste signal clears.

The controller comments on stuck PRs and may dispatch
`engineering-conflict-resolve.yml` for `cursor/eng-*` branches. It does **not**
merge. See [`project-traffic.md`](project-traffic.md).

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
