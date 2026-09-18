# Project traffic — end-of-day digest

Generated: `2026-09-18T07:46:57.804551+00:00`
Trajectory: **on_track**
Dispatch pause: **inactive** (stuck PRs: 0)

## Achieved (grounded)
- Infrastructure and offline library are ahead of schedule; the primary AI learning track is running but not yet beating the market.
- FTSE 350 live screen and published dashboard are operational.
- Offline library: 21 graduated markets (focus: euro_depth).
- Ops automation in place: daily monitor, tier-1 backup, external cron scheduling.
- Engineering queue: 2 open, 19 merged supervised tasks.

## Gaps / watch
- Primary AI track still below ^FTSE after costs (-31.8% excess; history still thin).
- Published screen bundle dated 2026-09-15 — confirm Sunday refresh.

## Checkpoint probe
- Grounded rows: 9; ungrounded: 0
- [ok] Stage 0 (UK quant core): complete _(source: docs/data/project_progress.json)_
- [ok] Stage 1 (Decision-review learning): in_progress _(source: docs/data/project_progress.json)_
- [ok] Stage 2b (Primary learning track): in_progress _(source: docs/data/project_progress.json)_
- [ok] Stage 3 (Library-ready global data): complete _(source: docs/data/project_progress.json)_
- [ok] Stage 4 (Controlled universe expansion): not_started _(source: docs/data/project_progress.json)_
- [ok] Stage 5 (Self-improving automation): not_started _(source: docs/data/project_progress.json)_
- [ok] Queue health overall=active; headline=Merge lane active; agent lane active. _(source: docs/data/queue_health.json)_
- [ok] Ops monitor overall=ok at 2026-09-17T07:46:34.530264+00:00 _(source: docs/data/ops_status.json)_
- [ok] Traffic pause_active=False; stuck_pr_count=0 _(source: docs/data/engineering_tasks.json#traffic_control)_

## Traffic actions
- _(none)_

## Merges today (monitor independent verify)
- `compile_cap_drain`/verified PR #697 `eng-20260917-10` — fcf: Do not pass dividend or FCF Yield on Yahoo FCF 100.6m when screen TTM is ~27.4m and TTM is suppressed without stating which basis the family used; keep fcf
- `human`/human PR #692 `eng-20260917-08` — Enable cyclical_exposure for UK heavyside construction-materials names when GB volume language and cement-output “historic lows” are in the same tape [1/2]

## PR fix occasions — common failure reasons
- Occasion count: 1
- `ruff_format` — 1×

## Ops-monitor email handoff
- Email subject: `FTSE Ops Monitor — WARN`
- Findings: 1 (open=0, resolved=1)
- [resolved] WARN Orphaned pr_open engineering tasks — planned: `remediate_queue_merge_sync` (PM v1: recover/mark-merged engineering queue reconciliation; cleared lag=['none'])

## Merge authority
- Status: **scoped_auto_merge**
- Traffic controller does not merge. Scoped auto-merge may merge ci_fix, ingest_narrow / scoring_narrow (independent deterministic verify), and parked_hunter PRs. EOD lists today's merges for monitoring.

Regenerate: `ftse-project-traffic run --write-digest`
