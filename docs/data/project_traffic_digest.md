# Project traffic — end-of-day digest

Generated: `2026-09-16T20:20:35.725686+00:00`
Trajectory: **on_track**
Dispatch pause: **inactive** (stuck PRs: 0)

## Achieved (grounded)
- Infrastructure and offline library are ahead of schedule; the primary AI learning track is running but not yet beating the market.
- FTSE 350 live screen and published dashboard are operational.
- Offline library: 21 graduated markets (focus: euro_depth).
- Ops automation in place: daily monitor, tier-1 backup, external cron scheduling.
- Engineering queue: 9 open, 2 merged supervised tasks.

## Gaps / watch
- Primary AI track still below ^FTSE after costs (-28.6% excess; history still thin).

## Checkpoint probe
- Grounded rows: 11; ungrounded: 0
- [ok] Stage 0 (UK quant core): complete _(source: docs/data/project_progress.json)_
- [ok] Stage 1 (Decision-review learning): in_progress _(source: docs/data/project_progress.json)_
- [ok] Stage 2b (Primary learning track): in_progress _(source: docs/data/project_progress.json)_
- [ok] Stage 3 (Library-ready global data): complete _(source: docs/data/project_progress.json)_
- [ok] Stage 4 (Controlled universe expansion): not_started _(source: docs/data/project_progress.json)_
- [ok] Stage 5 (Self-improving automation): not_started _(source: docs/data/project_progress.json)_
- [ok] Progress report present (generated_at=2026-09-16T16:53:21+00:00) _(source: docs/data/progress_report.json)_
- [ok] So-what / human_gate keys present: ['counts', 'generated_at', 'high_severity', 'high_severity_groups', 'human_gate_groups', 'human_gates_preview'] _(source: docs/data/progress_report.json)_
- [ok] Queue health overall=active; headline=Merge lane active; agent lane active. _(source: docs/data/queue_health.json)_
- [ok] Ops monitor overall=warn at 2026-09-16T07:46:38.598120+00:00 _(source: docs/data/ops_status.json)_
- [ok] Traffic pause_active=False; stuck_pr_count=0 _(source: docs/data/engineering_tasks.json#traffic_control)_

## Traffic actions
- _(none)_

## Merges today (monitor independent verify)
- `human`/human PR #675 `eng-20260916-04` — Flag when [2/2]
- `ingest_narrow`/verified PR #674 `eng-20260916-03` — Workflow fix: ingest-loop failure on main
- `human`/human PR #669 `eng-20260916-02` — Hunt fetchable IR source for parked euro_stoxx50 leftover SAN.PA
- `human`/human PR #666 `eng-20260916-01` — Fail-closed or flag when screen FCF (1,059m) disagrees with Yahoo/filing FCF (852m) while TTM is suppressed and cashflow_metrics is null. Turn on healthcare_pri

## PR fix occasions — common failure reasons
- Occasion count: 1
- `ruff_format` — 1×

## Merge authority
- Status: **scoped_auto_merge**
- Traffic controller does not merge. Scoped auto-merge may merge ci_fix, ingest_narrow / scoring_narrow (independent deterministic verify), and parked_hunter PRs. EOD lists today's merges for monitoring.

Regenerate: `ftse-project-traffic run --write-digest`
