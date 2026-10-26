# Project traffic — end-of-day digest

Generated: `2026-10-26T17:32:53.271910+00:00`
Trajectory: **blocked_by_pr_queue**
Dispatch pause: **inactive** (stuck PRs: 1)

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
- Grounded rows: 12; ungrounded: 0
- [ok] Stage 0 (UK quant core): complete _(source: docs/data/project_progress.json)_
- [ok] Stage 1 (Decision-review learning): in_progress _(source: docs/data/project_progress.json)_
- [ok] Stage 2b (Primary learning track): in_progress _(source: docs/data/project_progress.json)_
- [ok] Stage 3 (Library-ready global data): complete _(source: docs/data/project_progress.json)_
- [ok] Stage 4 (Controlled universe expansion): not_started _(source: docs/data/project_progress.json)_
- [ok] Stage 5 (Self-improving automation): not_started _(source: docs/data/project_progress.json)_
- [ok] Progress report present (generated_at=2026-09-30T20:08:50+00:00) _(source: docs/data/progress_report.json)_
- [ok] So-what / human_gate keys present: ['counts', 'generated_at', 'high_severity', 'high_severity_groups', 'human_gate_groups', 'human_gates_preview', 'learning_path_gap_groups'] _(source: docs/data/progress_report.json)_
- [ok] Queue health overall=active; headline=Agent lane active. _(source: docs/data/queue_health.json)_
- [ok] Ops monitor overall=warn at 2026-10-26T07:46:45.832559+00:00 _(source: docs/data/ops_status.json)_
- [ok] Traffic pause_active=False; stuck_pr_count=1 _(source: docs/data/engineering_tasks.json#traffic_control)_
- [ok] Stuck PR #1198 `cursor/blind-autopsy-split-defers-8f59` reasons=['merge_conflict'] mergeable_state=dirty _(source: github.pulls + check-runs)_

## Traffic actions
- `request_conflict_resolve` PR #1198 — comment posted (applied)

## Merges today (monitor independent verify)
- `human`/human PR #1200 `eng-20261026-04` — Hunt fetchable IR source for parked omxs30 leftover LIFCO-B.ST
- `parked_hunter`/verified PR #1199 `eng-20261026-03` — Hunt fetchable IR source for parked euro_stoxx50 leftover NOKIA.HE
- `human`/human PR #1192 `eng-20261026-02` — Close library ingest gaps for dax / HEI.DE (chain 1/3: 0/0 improved, run igc-20260922-07)

## PR fix occasions — common failure reasons
- Occasion count: 291
- `PR mergeable=CONFLICTING against main` — 7×
- `PR mergeable=CONFLICTING / mergeStateStatus=DIRTY against main` — 5×
- `merge_conflict:dirty` — 5×
- `validate check failed` — 4×
- `validate job failed` — 3×
- `validate failed` — 3×
- `deferred-ideas.json conflict after L516 merge` — 3×
- `ruff_format` — 2×

## Merge authority
- Status: **scoped_auto_merge**
- Traffic controller does not merge. Scoped auto-merge may merge ci_fix, ingest_narrow / scoring_narrow (independent deterministic verify), and parked_hunter PRs. EOD lists today's merges for monitoring.

Regenerate: `ftse-project-traffic run --write-digest`
