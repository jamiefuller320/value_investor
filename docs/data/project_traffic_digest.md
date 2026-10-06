# Project traffic — end-of-day digest

Generated: `2026-10-06T17:31:59.418835+00:00`
Trajectory: **blocked_by_pr_queue**
Dispatch pause: **active** (stuck PRs: 2)

## Achieved (grounded)
- Infrastructure and offline library are ahead of schedule; the primary AI learning track is running but not yet beating the market.
- FTSE 350 live screen and published dashboard are operational.
- Offline library: 21 graduated markets (focus: euro_depth).
- Ops automation in place: daily monitor, tier-1 backup, external cron scheduling.
- Engineering queue: 0 open, 96 merged supervised tasks.

## Gaps / watch
- Primary AI track still below ^FTSE after costs (-36.4% excess; history still thin).
- Published screen bundle dated 2026-09-27 — confirm Sunday refresh.

## Checkpoint probe
- Grounded rows: 13; ungrounded: 0
- [ok] Stage 0 (UK quant core): complete _(source: docs/data/project_progress.json)_
- [ok] Stage 1 (Decision-review learning): in_progress _(source: docs/data/project_progress.json)_
- [ok] Stage 2b (Primary learning track): in_progress _(source: docs/data/project_progress.json)_
- [ok] Stage 3 (Library-ready global data): complete _(source: docs/data/project_progress.json)_
- [ok] Stage 4 (Controlled universe expansion): not_started _(source: docs/data/project_progress.json)_
- [ok] Stage 5 (Self-improving automation): not_started _(source: docs/data/project_progress.json)_
- [ok] Progress report present (generated_at=2026-09-30T20:08:50+00:00) _(source: docs/data/progress_report.json)_
- [ok] So-what / human_gate keys present: ['counts', 'generated_at', 'high_severity', 'high_severity_groups', 'human_gate_groups', 'human_gates_preview', 'learning_path_gap_groups'] _(source: docs/data/progress_report.json)_
- [ok] Queue health overall=blocked; headline=Traffic pause — 0 stuck PR(s). project traffic pause (0 stuck PR(s); stuck_prs) — clear CI failures / merge conflicts before new PR generation _(source: docs/data/queue_health.json)_
- [ok] Ops monitor overall=warn at 2026-10-06T09:09:00.529194+00:00 _(source: docs/data/ops_status.json)_
- [ok] Traffic pause_active=True; stuck_pr_count=2 _(source: docs/data/engineering_tasks.json#traffic_control)_
- [ok] Stuck PR #994 `cursor/euro-national-oam-filings-de1b` reasons=['merge_conflict'] mergeable_state=dirty _(source: github.pulls + check-runs)_

## Traffic actions
- `pause_dispatch` — paused — 2 stuck PR(s); reasons=['merge_conflict'] (applied)
- `request_conflict_resolve` PR #994 — comment posted (applied)
- `request_conflict_resolve` PR #993 — comment posted (applied)

## Merges today (monitor independent verify)
- `human`/human PR #974 `eng-20261005-01` — Close library ingest filing gaps for FTSE MIB (ftse_mib): 1 buy-tier gaps after stalled weekday loop

## PR fix occasions — common failure reasons
- Occasion count: 164
- `PR mergeable=CONFLICTING against main` — 7×
- `PR mergeable=CONFLICTING / mergeStateStatus=DIRTY against main` — 5×
- `validate check failed` — 3×
- `deferred-ideas.json conflict after L516 merge` — 3×
- `Merge conflicts in deferred-ideas.json with main` — 2×
- `validate job failed` — 2×
- `Ruff F841 unused dismissable in market_warning_triage.propose_triage` — 2×
- `merge_conflict:dirty` — 2×

## Merge authority
- Status: **scoped_auto_merge**
- Traffic controller does not merge. Scoped auto-merge may merge ci_fix, ingest_narrow / scoring_narrow (independent deterministic verify), and parked_hunter PRs. EOD lists today's merges for monitoring.

Regenerate: `ftse-project-traffic run --write-digest`
