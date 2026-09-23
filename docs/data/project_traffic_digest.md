# Project traffic — end-of-day digest

Generated: `2026-09-23T20:36:52.646641+00:00`
Trajectory: **blocked_by_pr_queue**
Dispatch pause: **inactive** (stuck PRs: 1)

## Achieved (grounded)
- Infrastructure and offline library are ahead of schedule; the primary AI learning track is running but not yet beating the market.
- FTSE 350 live screen and published dashboard are operational.
- Offline library: 21 graduated markets (focus: euro_depth).
- Ops automation in place: daily monitor, tier-1 backup, external cron scheduling.
- Engineering queue: 0 open, 84 merged supervised tasks.

## Gaps / watch
- Primary AI track still below ^FTSE after costs (-34.0% excess; history still thin).
- Ingest coverage gap: 1 buy-tier tickers have no filings index yet.

## Checkpoint probe
- Grounded rows: 12; ungrounded: 0
- [ok] Stage 0 (UK quant core): complete _(source: docs/data/project_progress.json)_
- [ok] Stage 1 (Decision-review learning): in_progress _(source: docs/data/project_progress.json)_
- [ok] Stage 2b (Primary learning track): in_progress _(source: docs/data/project_progress.json)_
- [ok] Stage 3 (Library-ready global data): complete _(source: docs/data/project_progress.json)_
- [ok] Stage 4 (Controlled universe expansion): not_started _(source: docs/data/project_progress.json)_
- [ok] Stage 5 (Self-improving automation): not_started _(source: docs/data/project_progress.json)_
- [ok] Progress report present (generated_at=2026-09-22T08:34:03+00:00) _(source: docs/data/progress_report.json)_
- [ok] So-what / human_gate keys present: ['counts', 'generated_at', 'high_severity', 'high_severity_groups', 'human_gate_groups', 'human_gates_preview', 'learning_path_gap_groups'] _(source: docs/data/progress_report.json)_
- [ok] Queue health overall=idle; headline=Queue and hunter idle. _(source: docs/data/queue_health.json)_
- [ok] Ops monitor overall=warn at 2026-09-23T07:46:36.280037+00:00 _(source: docs/data/ops_status.json)_
- [ok] Traffic pause_active=False; stuck_pr_count=1 _(source: docs/data/engineering_tasks.json#traffic_control)_
- [ok] Stuck PR #828 `cursor/ingest-deviation-signal-triage-defer-f703` reasons=['merge_conflict'] mergeable_state=dirty _(source: github.pulls + check-runs)_

## Traffic actions
- `request_conflict_resolve` PR #828 — comment posted (applied)

## Merges today (monitor independent verify)
- `human`/human PR #827 `eng-20260923-09` — Close library ingest filing gaps for DAX (dax): 1 buy-tier gaps after stalled weekday loop
- `human`/human PR #818 `eng-20260922-05` — Close library ingest filing gaps for DAX (dax): 6 buy-tier gaps after stalled weekday loop
- `human`/human PR #825 `eng-20260923-08` — Rework verify round 2/3: IR presentation allowlist + parser to `ir_presentation_metrics.json` (statutory-to-adjusted FCF bridges, segment tables) for top FCF-di
- `human`/human PR #823 `eng-20260923-05` — Body-lag rememo gate: after new filing bodies land, rememo thin/zero-body euro_depth memos without widening generic rememo_reason; tie ladder eligibility to bod
- `human`/human PR #824 `eng-20260923-04` — Companies House group accounts: iXBRL-first with OCR fallback, quality gate rejecting garbled bodies
- `scoring_narrow`/verified PR #822 `eng-20260923-07` — Honour FCF action-note enforcement (batched tickers)
- `human`/human PR #821 `eng-20260923-03` — dividend: Statutory FCF/dividend primary overlay plus company-adjusted FCF bind to latest filing year with staleness flag when screen numerator lags [2/2]
- `scoring_narrow`/verified PR #820 `eng-20260923-06` — Close FCF basis enforcement gap (batched tickers)
- `human`/human PR #819 `eng-20260923-02` — fcf: Statutory FCF/dividend primary overlay plus company-adjusted FCF bind to latest filing year with staleness flag when screen numerator lags [1/2]
- `human`/human PR #816 `eng-20260923-01` — Expand IR presentation pipeline: allowlist FY/H1 PDFs, non-truncated text extract, and structured parse into `ir_presentation_metrics.json` (FCF/dividend bridge

## PR fix occasions — common failure reasons
- Occasion count: 33
- `PR mergeable=CONFLICTING against main` — 7×
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
