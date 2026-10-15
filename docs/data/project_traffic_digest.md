# Project traffic — end-of-day digest

Generated: `2026-10-15T17:32:12.902095+00:00`
Trajectory: **on_track**
Dispatch pause: **inactive** (stuck PRs: 0)

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
- [ok] Queue health overall=blocked; headline=1 open task(s) blocked by file clash or policy — no open engineering tasks in queue _(source: docs/data/queue_health.json)_
- [ok] Ops monitor overall=warn at 2026-10-15T07:36:10.066728+00:00 _(source: docs/data/ops_status.json)_
- [ok] Traffic pause_active=False; stuck_pr_count=0 _(source: docs/data/engineering_tasks.json#traffic_control)_

## Traffic actions
- _(none)_

## Merges today (monitor independent verify)
- `human`/human PR #1093 `eng-20261015-03` — Seed IR allowlist for unmeasured/zero-body KGF.L — empty allowlist after 0-improve pin (igc-20261015-02)
- `parked_hunter`/verified PR #1092 `eng-20261013-04` — Hunt fetchable IR source for parked aim leftover YNGN.L
- `parked_hunter`/verified PR #1090 `eng-20261015-02` — Hunt fetchable IR source for parked sp500 leftover EME
- `human`/human PR #1088 `eng-20261014-02` — Close stubborn ingest gaps for SHEL.L (chain 1/3: 0/0 bodies, run igc-20261014-03)
- `parked_hunter`/verified PR #1089 `eng-20261015-01` — Hunt fetchable IR source for parked euro_depth leftover PRX.AS
- `parked_hunter`/verified PR #1076 `eng-20261014-01` — Hunt fetchable IR source for parked sp500 leftover LH

## PR fix occasions — common failure reasons
- Occasion count: 215
- `PR mergeable=CONFLICTING against main` — 7×
- `PR mergeable=CONFLICTING / mergeStateStatus=DIRTY against main` — 5×
- `validate check failed` — 4×
- `validate failed` — 3×
- `deferred-ideas.json conflict after L516 merge` — 3×
- `merge_conflict:dirty` — 3×
- `Merge conflicts in deferred-ideas.json with main` — 2×
- `validate job failed` — 2×

## Merge authority
- Status: **scoped_auto_merge**
- Traffic controller does not merge. Scoped auto-merge may merge ci_fix, ingest_narrow / scoring_narrow (independent deterministic verify), and parked_hunter PRs. EOD lists today's merges for monitoring.

Regenerate: `ftse-project-traffic run --write-digest`
