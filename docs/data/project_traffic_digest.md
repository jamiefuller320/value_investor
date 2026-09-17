# Project traffic — end-of-day digest

Generated: `2026-09-17T20:28:56.678903+00:00`
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
- `remediate_queue_merge_sync` — detected merge sync lag for 1 task(s): eng-20260917-08 (not applied)
- `remediate_queue_merge_sync` — PM remediated queue merge sync: fixed=['eng-20260917-08']; remaining=['none'] (applied)

## Merges today (monitor independent verify)
- `human`/human PR #691 `eng-20260917-08` — Enable cyclical_exposure for UK heavyside construction-materials names when GB volume language and cement-output “historic lows” are in the same tape [1/2]
- `ci_fix`/verified PR #686 `eng-20260917-06` — fcf: Do not pass dividend or FCF Yield on company-adjusted FCF (£73.8m) when filing FCF is 5× larger without stating which basis the family used; keep fcf_defin
- `compile_cap_drain`/verified PR #685 `eng-20260917-05` — Relabel `adjusted_eps_growth_pct` when sourced from Yahoo Normalized Income (MEGP: no adjusted EPS in 67 filing bodies) to stop false “filing core” Lynch PEG fa
- `human`/human PR #682 `eng-20260917-04` — Set fcf_definition_divergence whenever filing/Yahoo 1,861m and screen TTM 1,200.4m disagree; do not pass FCF Yield at 9.3% or a 4.0% dividend without stating th
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
