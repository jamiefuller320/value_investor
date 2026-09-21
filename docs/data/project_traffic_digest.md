# Project traffic — end-of-day digest

Generated: `2026-09-21T18:56:44.883412+00:00`
Trajectory: **on_track**
Dispatch pause: **inactive** (stuck PRs: 0)

## Achieved (grounded)
- Infrastructure and offline library are ahead of schedule; the primary AI learning track is running but not yet beating the market.
- FTSE 350 live screen and published dashboard are operational.
- Offline library: 21 graduated markets (focus: euro_depth).
- Ops automation in place: daily monitor, tier-1 backup, external cron scheduling.
- Engineering queue: 0 open, 71 merged supervised tasks.

## Gaps / watch
- Primary AI track still below ^FTSE after costs (-33.0% excess; history still thin).
- Ingest coverage gap: 3 buy-tier tickers have no filings index yet.

## Checkpoint probe
- Grounded rows: 9; ungrounded: 0
- [ok] Stage 0 (UK quant core): complete _(source: docs/data/project_progress.json)_
- [ok] Stage 1 (Decision-review learning): in_progress _(source: docs/data/project_progress.json)_
- [ok] Stage 2b (Primary learning track): in_progress _(source: docs/data/project_progress.json)_
- [ok] Stage 3 (Library-ready global data): complete _(source: docs/data/project_progress.json)_
- [ok] Stage 4 (Controlled universe expansion): not_started _(source: docs/data/project_progress.json)_
- [ok] Stage 5 (Self-improving automation): not_started _(source: docs/data/project_progress.json)_
- [ok] Queue health overall=idle; headline=Queue and hunter idle. _(source: docs/data/queue_health.json)_
- [ok] Ops monitor overall=warn at 2026-09-20T07:46:35.090327+00:00 _(source: docs/data/ops_status.json)_
- [ok] Traffic pause_active=False; stuck_pr_count=0 _(source: docs/data/engineering_tasks.json#traffic_control)_

## Traffic actions
- _(none)_

## Merges today (monitor independent verify)
- `human`/human PR #782 `eng-20260921-03` — Implement canonical FCF basis selector for overlays (filing-year statutory OCF−CapEx vs company-adjusted vs screen TTM) with explicit stale-year flag when scree
- `human`/human PR #783 `eng-20260921-02` — Fix Companies House PDF/iXBRL download and OCR quality gate (retry, iXBRL-first, reject garbled OCR)—target ITV.L/MGNS.L failure modes cited in recent suggestio
- `human`/human PR #776 `eng-20260921-05` — Wire `operating_cashflow` (and related cash-flow fields) from `financials_annual.json` into `CompanyMetrics` when Yahoo fetch returns None—validate on MEGP.L be
- `human`/human PR #777 `eng-20260921-04` — Standardize IR results-presentation ingest: allowlist fetch, full-text extract, and populate `ir_presentation_metrics.json` FCF/dividend bridges (FGP.L FY2026 r
- `human`/human PR #773 `eng-20260921-01` — Harden Investegate/LSE direct fetch for indexed RNS items (FY/HY results, annual reports)—replace Google News wrapper URLs and empty Ticker RNS bodies—starting

## PR fix occasions — common failure reasons
- Occasion count: 14
- `PR mergeable=CONFLICTING against main` — 4×
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
