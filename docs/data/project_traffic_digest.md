# Project traffic — end-of-day digest

Generated: `2026-09-21T07:46:52.025232+00:00`
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
- [ok] Queue health overall=active; headline=Agent lane active. _(source: docs/data/queue_health.json)_
- [ok] Ops monitor overall=warn at 2026-09-20T07:46:35.090327+00:00 _(source: docs/data/ops_status.json)_
- [ok] Traffic pause_active=False; stuck_pr_count=0 _(source: docs/data/engineering_tasks.json#traffic_control)_

## Traffic actions
- _(none)_

## Merges today (monitor independent verify)
- `human`/human PR #773 `eng-20260921-01` — Close stubborn ingest gaps for GFTU.L (chain 1/3: 0/234 bodies, run igc-20260921-01)

## PR fix occasions — common failure reasons
- Occasion count: 11
- `PR mergeable=CONFLICTING against main` — 2×
- `ruff_format` — 1×
- `dirty merge: deferred-ideas.json / deferred-review.md vs main after L424-L426 landings` — 1×
- `dirty merge: engineering_tasks/automation/queue_health stale vs merged salvage PRs #726-#728` — 1×
- `pytest test_summary: WIX/BT action notes lost screen TTM after overly broad eng-20260919-14 suppress` — 1×
- `engineering_tasks.json queue_clearing + automation.json queue snapshots vs main (#757 ledger)` — 1×
- `engineering_tasks/automation/queue_health vs main after #756 merge` — 1×
- `PR mergeable=CONFLICTING / mergeStateStatus=DIRTY against main` — 1×

## Ops-monitor email handoff
- Email subject: `FTSE Ops Monitor — WARN`
- Findings: 1 (open=1, resolved=0)
- [open] WARN Parked engineering tasks need manual review — planned: `human_triage` (Surface in PM digest for human / eng follow-up)

## Merge authority
- Status: **scoped_auto_merge**
- Traffic controller does not merge. Scoped auto-merge may merge ci_fix, ingest_narrow / scoring_narrow (independent deterministic verify), and parked_hunter PRs. EOD lists today's merges for monitoring.

Regenerate: `ftse-project-traffic run --write-digest`
