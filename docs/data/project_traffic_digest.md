# Project traffic — end-of-day digest

Generated: `2026-09-22T20:21:29.286725+00:00`
Trajectory: **on_track**
Dispatch pause: **inactive** (stuck PRs: 0)

## Achieved (grounded)
- Infrastructure and offline library are ahead of schedule; the primary AI learning track is running but not yet beating the market.
- FTSE 350 live screen and published dashboard are operational.
- Offline library: 21 graduated markets (focus: euro_depth).
- Ops automation in place: daily monitor, tier-1 backup, external cron scheduling.
- Engineering queue: 0 open, 72 merged supervised tasks.

## Gaps / watch
- Primary AI track still below ^FTSE after costs (-32.3% excess; history still thin).
- Ingest coverage gap: 4 buy-tier tickers have no filings index yet.

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
- [ok] Queue health overall=blocked; headline=Traffic pause — 0 stuck PR(s). project traffic pause (0 stuck PR(s); stuck_prs) — clear CI failures / merge conflicts before new PR generation _(source: docs/data/queue_health.json)_
- [ok] Ops monitor overall=warn at 2026-09-22T07:46:36.040299+00:00 _(source: docs/data/ops_status.json)_
- [ok] Traffic pause_active=False; stuck_pr_count=0 _(source: docs/data/engineering_tasks.json#traffic_control)_

## Traffic actions
- `resume_dispatch` — resumed — no stuck monitored PRs and idle window elapsed (applied)

## Merges today (monitor independent verify)
- `ingest_narrow`/verified PR #804 `eng-20260922-04` — Close stubborn ingest gaps for SHEL.L (chain 1/3: 0/0 bodies, run igc-20260922-04)
- `ingest_narrow`/verified PR #803 `eng-20260922-03` — Close stubborn ingest gaps for KGF.L (chain 1/3: 0/0 bodies, run igc-20260922-03)
- `human`/human PR #797 `eng-20260922-02` — Close stubborn ingest gaps for VTY.L (chain 1/3: 0/0 bodies, run igc-20260922-01)

## PR fix occasions — common failure reasons
- Occasion count: 27
- `PR mergeable=CONFLICTING against main` — 4×
- `Merge conflicts in deferred-ideas.json with main` — 2×
- `ruff_format` — 1×
- `dirty merge: deferred-ideas.json / deferred-review.md vs main after L424-L426 landings` — 1×
- `dirty merge: engineering_tasks/automation/queue_health stale vs merged salvage PRs #726-#728` — 1×
- `pytest test_summary: WIX/BT action notes lost screen TTM after overly broad eng-20260919-14 suppress` — 1×
- `engineering_tasks.json queue_clearing + automation.json queue snapshots vs main (#757 ledger)` — 1×
- `engineering_tasks/automation/queue_health vs main after #756 merge` — 1×

## Merge authority
- Status: **scoped_auto_merge**
- Traffic controller does not merge. Scoped auto-merge may merge ci_fix, ingest_narrow / scoring_narrow (independent deterministic verify), and parked_hunter PRs. EOD lists today's merges for monitoring.

Regenerate: `ftse-project-traffic run --write-digest`
