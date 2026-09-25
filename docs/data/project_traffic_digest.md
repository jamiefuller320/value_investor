# Project traffic — end-of-day digest

Generated: `2026-09-25T07:47:21.653112+00:00`
Trajectory: **blocked_by_pr_queue**
Dispatch pause: **active** (stuck PRs: 0)

## Achieved (grounded)
- Infrastructure and offline library are ahead of schedule; the primary AI learning track is running but not yet beating the market.
- FTSE 350 live screen and published dashboard are operational.
- Offline library: 21 graduated markets (focus: euro_depth).
- Ops automation in place: daily monitor, tier-1 backup, external cron scheduling.
- Engineering queue: 0 open, 84 merged supervised tasks.

## Gaps / watch
- Primary AI track still below ^FTSE after costs (-34.0% excess; history still thin).
- Ingest coverage gap: 1 buy-tier tickers have no filings index yet.

## Checkpoint probe
- Grounded rows: 11; ungrounded: 0
- [ok] Stage 0 (UK quant core): complete _(source: docs/data/project_progress.json)_
- [ok] Stage 1 (Decision-review learning): in_progress _(source: docs/data/project_progress.json)_
- [ok] Stage 2b (Primary learning track): in_progress _(source: docs/data/project_progress.json)_
- [ok] Stage 3 (Library-ready global data): complete _(source: docs/data/project_progress.json)_
- [ok] Stage 4 (Controlled universe expansion): not_started _(source: docs/data/project_progress.json)_
- [ok] Stage 5 (Self-improving automation): not_started _(source: docs/data/project_progress.json)_
- [ok] Progress report present (generated_at=2026-09-22T08:34:03+00:00) _(source: docs/data/progress_report.json)_
- [ok] So-what / human_gate keys present: ['counts', 'generated_at', 'high_severity', 'high_severity_groups', 'human_gate_groups', 'human_gates_preview', 'learning_path_gap_groups'] _(source: docs/data/progress_report.json)_
- [ok] Queue health overall=blocked; headline=Traffic pause — 0 stuck PR(s). project traffic pause (automation_waste) — automation waste hold; clear reburn / parked tasks before new PR generation _(source: docs/data/queue_health.json)_
- [ok] Ops monitor overall=fail at 2026-09-24T17:51:52.496282+00:00 _(source: docs/data/ops_status.json)_
- [ok] Traffic pause_active=True; stuck_pr_count=0 _(source: docs/data/engineering_tasks.json#traffic_control)_

## Traffic actions
- `stop_automation_waste` — cleared automation-waste hold — no remediable signal (applied)

## Merges today (monitor independent verify)
- _(none merged today)_

## PR fix occasions — common failure reasons
- Occasion count: 55
- `PR mergeable=CONFLICTING against main` — 7×
- `PR mergeable=CONFLICTING / mergeStateStatus=DIRTY against main` — 5×
- `Merge conflicts in deferred-ideas.json with main` — 2×
- `ruff_format` — 1×
- `dirty merge: deferred-ideas.json / deferred-review.md vs main after L424-L426 landings` — 1×
- `dirty merge: engineering_tasks/automation/queue_health stale vs merged salvage PRs #726-#728` — 1×
- `pytest test_summary: WIX/BT action notes lost screen TTM after overly broad eng-20260919-14 suppress` — 1×
- `engineering_tasks.json queue_clearing + automation.json queue snapshots vs main (#757 ledger)` — 1×

## Ops-monitor email handoff
- Email subject: `FTSE Ops Monitor — FAIL`
- Findings: 6 (open=6, resolved=0)
- [open] WARN New buy-tier not yet usable — planned: `human_triage` (Surface in PM digest for human / eng follow-up)
- [open] WARN FTSE decision-input utilization gap — planned: `human_triage` (Surface in PM digest for human / eng follow-up)
- [open] WARN Lifecycle maturity mix trajectory stalled — planned: `human_triage` (Surface in PM digest for human / eng follow-up)
- [open] FAIL So-what learning gap active (thin_memo_counted_as_coverage) — planned: `draft_ops_engineering_task` (Draft supervised ops engineering task (ops-monitor draft path))
- [open] WARN Parked engineering tasks need manual review — planned: `human_triage` (Surface in PM digest for human / eng follow-up)
- [open] WARN Project traffic pause active — planned: `request_unstick_stuck_prs` (PM v1: traffic pause/unstick path (CI comment / conflict-resolve))

## Merge authority
- Status: **scoped_auto_merge**
- Traffic controller does not merge. Scoped auto-merge may merge ci_fix, ingest_narrow / scoring_narrow (independent deterministic verify), and parked_hunter PRs. EOD lists today's merges for monitoring.

Regenerate: `ftse-project-traffic run --write-digest`
