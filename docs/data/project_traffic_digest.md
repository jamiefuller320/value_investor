# Project traffic — end-of-day digest

Generated: `2026-11-10T12:32:54.039737+00:00`
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
- [ok] Queue health overall=idle; headline=Queue and hunter idle. _(source: docs/data/queue_health.json)_
- [ok] Ops monitor overall=warn at 2026-11-10T10:07:40.188733+00:00 _(source: docs/data/ops_status.json)_
- [ok] Traffic pause_active=False; stuck_pr_count=0 _(source: docs/data/engineering_tasks.json#traffic_control)_

## Traffic actions
- _(none)_

## Merges today (monitor independent verify)
- `human`/human PR #1345 `eng-20261110-09` — Workflow fix: library ingest maintenance failure
- `ingest_narrow`/verified PR #1344 `eng-20261110-08` — Buy-tier body-lag sweep job: prioritize BGEO.L, IAG.L, IGG.L, INCH.L from this run’s `filing_coverage.indexed_without_body` with success metrics and alert on ze
- `scoring_narrow`/verified PR #1343 `eng-20261110-07` — contractor: Agriculture/Commodities for plantation issuers, UK contractor backlog/margin hooks, healthcare negative-FCF + low Pio [4/4]
- `ingest_narrow`/verified PR #1342 `eng-20261110-03` — Allowlisted company IR results-presentation PDF fetch (pattern in `gap_fill_source_map` / high-priority HIK.L, MEGP.L samples)
- `scoring_narrow`/verified PR #1341 `eng-20261110-06` — healthcare: Agriculture/Commodities for plantation issuers, UK contractor backlog/margin hooks, healthcare negative-FCF + low Pio [3/4]
- `human`/human PR #1340 `eng-20261110-02` — Harden Companies House filed-accounts PDF download + text/OCR pipeline using existing `document-api` URLs in `filings_index.json`
- `scoring_narrow`/verified PR #1339 `eng-20261110-05` — fcf: Agriculture/Commodities for plantation issuers, UK contractor backlog/margin hooks, healthcare negative-FCF + low Pio [2/4]
- `human`/human PR #1338 `eng-20261110-01` — Ship unified Investegate/LSE direct fetch for indexed RNS items (replace Google News redirect URLs, PDF/HTML body persist to `filings/bodies/`)
- `scoring_narrow`/verified PR #1337 `eng-20261110-04` — Sector and cyclical overlay registry (e.g [1/4]
- `human`/human PR #1334 `eng-20261109-01` — Hunt fetchable IR source for parked asx200 leftover IMD.AX

## PR fix occasions — common failure reasons
- Occasion count: 358
- `PR mergeable=CONFLICTING against main` — 7×
- `validate failed` — 7×
- `validate check failed` — 6×
- `merge_conflict:dirty` — 6×
- `PR mergeable=CONFLICTING / mergeStateStatus=DIRTY against main` — 5×
- `validate job failed` — 3×
- `deferred-ideas.json conflict after L516 merge` — 3×
- `ruff_format` — 2×

## Merge authority
- Status: **scoped_auto_merge**
- Traffic controller does not merge. Scoped auto-merge may merge ci_fix, ingest_narrow / scoring_narrow (independent deterministic verify), and parked_hunter PRs. EOD lists today's merges for monitoring.

Regenerate: `ftse-project-traffic run --write-digest`
