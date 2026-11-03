# Project traffic — end-of-day digest

Generated: `2026-11-03T12:33:12.454462+00:00`
Trajectory: **blocked_by_pr_queue**
Dispatch pause: **active** (stuck PRs: 0)

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
- Grounded rows: 11; ungrounded: 0
- [ok] Stage 0 (UK quant core): complete _(source: docs/data/project_progress.json)_
- [ok] Stage 1 (Decision-review learning): in_progress _(source: docs/data/project_progress.json)_
- [ok] Stage 2b (Primary learning track): in_progress _(source: docs/data/project_progress.json)_
- [ok] Stage 3 (Library-ready global data): complete _(source: docs/data/project_progress.json)_
- [ok] Stage 4 (Controlled universe expansion): not_started _(source: docs/data/project_progress.json)_
- [ok] Stage 5 (Self-improving automation): not_started _(source: docs/data/project_progress.json)_
- [ok] Progress report present (generated_at=2026-09-30T20:08:50+00:00) _(source: docs/data/progress_report.json)_
- [ok] So-what / human_gate keys present: ['counts', 'generated_at', 'high_severity', 'high_severity_groups', 'human_gate_groups', 'human_gates_preview', 'learning_path_gap_groups'] _(source: docs/data/progress_report.json)_
- [ok] Queue health overall=idle; headline=Queue and hunter idle. _(source: docs/data/queue_health.json)_
- [ok] Ops monitor overall=warn at 2026-11-03T07:47:09.251906+00:00 _(source: docs/data/ops_status.json)_
- [ok] Traffic pause_active=True; stuck_pr_count=0 _(source: docs/data/engineering_tasks.json#traffic_control)_

## Traffic actions
- `stop_automation_waste` — signals=1; parked=eng-20261103-07; pause=True (applied)
- `pause_dispatch` — paused — 0 stuck PR(s); reasons=['automation_waste'] (applied)

## Merges today (monitor independent verify)
- `parked_hunter`/verified PR #1269 `eng-20261103-02` — Hunt fetchable IR source for parked tsx60 leftover ABX.TO
- `parked_hunter`/verified PR #1265 `eng-20261103-06` — Hunt fetchable IR source for parked tsx60 leftover MG.TO
- `parked_hunter`/verified PR #1264 `eng-20261103-05` — Hunt fetchable IR source for parked asx200 leftover NEM.AX
- `parked_hunter`/verified PR #1263 `eng-20261103-04` — Hunt fetchable IR source for parked tsx60 leftover TECK-B.TO
- `parked_hunter`/verified PR #1262 `eng-20261103-03` — Hunt fetchable IR source for parked tsx60 leftover SAP.TO
- `parked_hunter`/verified PR #1261 `eng-20261103-01` — Hunt fetchable IR source for parked aex leftover SHELL.AS
- `parked_hunter`/verified PR #1260 `eng-20261102-03` — Hunt fetchable IR source for parked sp500 leftover COR
- `human`/human PR #1256 `eng-20261102-02` — Close library ingest gaps for sti / U14.SI (chain 1/3: 0/0 improved, run igc-20261026-02)

## PR fix occasions — common failure reasons
- Occasion count: 322
- `PR mergeable=CONFLICTING against main` — 7×
- `validate failed` — 7×
- `merge_conflict:dirty` — 6×
- `PR mergeable=CONFLICTING / mergeStateStatus=DIRTY against main` — 5×
- `validate check failed` — 5×
- `validate job failed` — 3×
- `deferred-ideas.json conflict after L516 merge` — 3×
- `ruff_format` — 2×

## Merge authority
- Status: **scoped_auto_merge**
- Traffic controller does not merge. Scoped auto-merge may merge ci_fix, ingest_narrow / scoring_narrow (independent deterministic verify), and parked_hunter PRs. EOD lists today's merges for monitoring.

Regenerate: `ftse-project-traffic run --write-digest`
