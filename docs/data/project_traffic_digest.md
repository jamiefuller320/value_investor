# Project traffic — end-of-day digest

Generated: `2026-09-17T07:47:00.497170+00:00`
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
- `human`/human PR #681 `eng-20260917-03` — Set fcf_definition_divergence whenever retail ~£574m, Yahoo £923m and screen £645m disagree; do not pass FCF Yield at 8.8% or High Dividend Yield at 4.1% withou
- `parked_hunter`/verified PR #680 `eng-20260916-06` — Hunt fetchable IR source for parked asx200 leftover BPT.AX
- `compile_cap_drain`/verified PR #679 `eng-20260917-02` — Set fcf_definition_divergence whenever filing ~£462m, Yahoo £956m and screen £830m disagree; do not pass FCF Yield at 21.4% without stating the basis [1/2]

## PR fix occasions — common failure reasons
- Occasion count: 1
- `ruff_format` — 1×

## Merge authority
- Status: **scoped_auto_merge**
- Traffic controller does not merge. Scoped auto-merge may merge ci_fix, ingest_narrow / scoring_narrow (independent deterministic verify), and parked_hunter PRs. EOD lists today's merges for monitoring.

Regenerate: `ftse-project-traffic run --write-digest`
