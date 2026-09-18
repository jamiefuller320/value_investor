# Project traffic — end-of-day digest

Generated: `2026-09-18T16:39:00.683864+00:00`
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
- [ok] Queue health overall=blocked; headline=1 open task(s) blocked by file clash or policy — no open engineering tasks in queue _(source: docs/data/queue_health.json)_
- [ok] Ops monitor overall=warn at 2026-09-18T07:46:32.075815+00:00 _(source: docs/data/ops_status.json)_
- [ok] Traffic pause_active=False; stuck_pr_count=0 _(source: docs/data/engineering_tasks.json#traffic_control)_

## Traffic actions
- _(none)_

## Merges today (monitor independent verify)
- `compile_cap_drain`/verified PR #714 `eng-20260918-14` — Four worker types plus a five-task cap force annual + interim + news + screen + gap and leave no slot for the Sky sale body (10f52d865099383d), Q1 2026 trading
- `compile_cap_drain`/verified PR #713 `eng-20260918-10` — When a sal [2/2]
- `compile_cap_drain`/verified PR #712 `eng-20260918-11` — Require annual/interim workers to extract continuing versus discontinued / held-for-sale splits, deal terms, guidance, FCF versus dividend cover, and reporting 
- `compile_cap_drain`/verified PR #711 `eng-20260918-09` — Select the latest dated annual and interim *results* bodies (FY25 29bdb56d3cedb539, H1 2026 d19c5d3b8e0bb46a — not the 30 June period-end duplicate) [1/2]
- `compile_cap_drain`/verified PR #710 `eng-20260918-01` — dividend: Do not pass dividend or FCF Yield on Yahoo FCF 100.6m when screen TTM is ~27.4m and TTM is suppressed without stating which basis the family used; kee
- `compile_cap_drain`/verified PR #709 `eng-20260918-08` — dividend: Require explicit **dual FCF dividend cover** (statutory OCF−CapEx vs management “cash generated from operations”−CapEx) in research prompts when `fcf_
- `compile_cap_drain`/verified PR #706 `eng-20260918-07` — fcf: Require explicit **dual FCF dividend cover** (statutory OCF−CapEx vs management “cash generated from operations”−CapEx) in research prompts when `fcf_defin
- `ci_fix`/verified PR #704 `eng-20260918-05` — dividend: Primary dividend-sustainability overlay on statutory FCF/dividend; warn when interim dividend is cut despite high trailing yield pass. [2/2]
- `compile_cap_drain`/verified PR #703 `eng-20260918-04` — fcf: Primary dividend-sustainability overlay on statutory FCF/dividend; warn when interim dividend is cut despite high trailing yield pass. [1/2]
- `compile_cap_drain`/verified PR #702 `eng-20260918-03` — fcf: Media cyclicality + thin FCF coverage overlay (advertising >40%, Piotroski ≤4, statutory FCF/dividend ≤1.1×). [1/2]
- `compile_cap_drain`/verified PR #701 `eng-20260918-02` — Auto-flag cyclical exposure when principal-risk filings cite recession/discretionary spending and any interim month shows photobooth revenue decline >10% (MEGP
- `compile_cap_drain`/verified PR #699 `eng-20260917-01` — Do not pass dividend or FCF Yield on Yahoo FCF 100.6m when screen TTM is ~27.4m and TTM is suppressed without stating which basis the family used; keep fcf_defi
- `compile_cap_drain`/verified PR #697 `eng-20260917-10` — fcf: Do not pass dividend or FCF Yield on Yahoo FCF 100.6m when screen TTM is ~27.4m and TTM is suppressed without stating which basis the family used; keep fcf
- `human`/human PR #692 `eng-20260917-08` — Enable cyclical_exposure for UK heavyside construction-materials names when GB volume language and cement-output “historic lows” are in the same tape [1/2]

## PR fix occasions — common failure reasons
- Occasion count: 1
- `ruff_format` — 1×

## Merge authority
- Status: **scoped_auto_merge**
- Traffic controller does not merge. Scoped auto-merge may merge ci_fix, ingest_narrow / scoring_narrow (independent deterministic verify), and parked_hunter PRs. EOD lists today's merges for monitoring.

Regenerate: `ftse-project-traffic run --write-digest`
