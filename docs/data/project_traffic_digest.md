# Project traffic — end-of-day digest

Generated: `2026-09-15T20:21:43.825438+00:00`
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
- [ok] Progress report present (generated_at=2026-09-15T12:38:22+00:00) _(source: docs/data/progress_report.json)_
- [ok] So-what / human_gate keys present: ['counts', 'generated_at', 'high_severity', 'high_severity_groups', 'human_gate_groups', 'human_gates_preview'] _(source: docs/data/progress_report.json)_
- [ok] Queue health overall=active; headline=Agent lane active. _(source: docs/data/queue_health.json)_
- [ok] Ops monitor overall=ok at 2026-09-15T13:16:17.148729+00:00 _(source: docs/data/ops_status.json)_
- [ok] Traffic pause_active=False; stuck_pr_count=0 _(source: docs/data/engineering_tasks.json#traffic_control)_

## Traffic actions
- _(none)_

## Merge authority
- Status: **restricted**
- Traffic controller may pause dispatch and request fixes; it does not merge. Loosen only with independent verification (path guard + green CI + allowlist), same as scoped auto-merge.

Regenerate: `ftse-project-traffic run --write-digest`
