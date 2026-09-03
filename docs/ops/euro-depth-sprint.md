# euro_depth 30-day sprint (Phase 3 exit)

Aggressive depth-first schedule to reach **end of Phase 3** (~weekday paper shard complete)
in **~30 calendar days**, assuming daily automation and no long CI outages.

See also: [`market-sharded-learning.md`](market-sharded-learning.md), [`market-scrutiny.md`](market-scrutiny.md).

## What “end of Phase 3” means

| Gate | Sprint threshold | Default |
|------|------------------|---------|
| Phase 1 screen archives + observe snapshots | **4** each | 12 |
| Phase 2 weekly paper batches + `beat_control` | **4** batches | 8 |
| Phase 3 weekday paper batches | **8** batches | 8 |
| Phase 3 exit-shadow closed episodes | **8** (ai_judgment track) | 15 |

Policy knobs live in `docs/data/library/policy.json` → `ladder.*`.

Phase 3 is **complete** when `ftse-library shard-status --markets euro_depth` reports
`phase3_ready: true` (no blockers).

## Honest constraints

- **Filing parity** still depends on weekday `euro-ingest-loop` + ESEF/IR bodies — memos
  without bodies do not make AI tracks FTSE-equivalent.
- **Exit-shadow episodes** need closed paper trades; thin history may require lowering
  `phase3_min_exit_shadow_closed` for the sprint or running extra `shard-weekday` passes.
- **1 month is a sprint**, not the default promotion bar — revert compressed gates after
  the monthly `euro_depth` parity review passes.

## Automation stack (wired Aug 2026)

| Layer | Command / workflow | Cadence |
|-------|-------------------|---------|
| Metrics grow (full ~194) | `ftse-library grow --market euro_depth` | Day 1 burst (`focus_grow_cap: 200`) |
| Filing deepen (buy-tier) | `ftse-library ingest-loop --market euro_depth` | **7-day:** Mon–Sat peak + daily off-peak — **euro-ingest-loop.yml** on focus; **library-ingest-sprint.yml** on `ingest_parallel_sprint` (sp500); **library-ingest-sprint-2.yml** on `ingest_parallel_sprint_2` (asx200); **library-ingest-maintenance.yml** at FTSE volume once the quality bar is met |
| Screen + observe + weekly shard | `ftse-library ladder` | Daily `ladder_only` when eng idle + Sundays |
| Phase 3 weekday shard | `ftse-library shard-weekday --markets euro_depth` | Weekdays after Phase 2 gate |

### Completion gate (ingest throttle)

Sprint discovery is **time-capped** (`library_ingest_budget.py`): at most 25% of the
2700s slot, critical-path tickers first, so body deepen is not starved when
`force_discovery_scan` is on.

After a **complete** deepen that is stalled or improves nobody while gaps remain,
`euro-ingest-loop.yml` auto-dispatches a pinned intensive gap-closure pass
(`gap_closure_trigger=stall_slowdown`) for the stickiest buy-tier name. Partial /
runtime-cutoff runs do not escalate — the discovery cap is the fix for those.

`ftse-library euro-ingest-dispatch` evaluates **buy-tier filing parity** on the focus market
and persists `docs/data/library/euro_ingest_dispatch.json`:

| Mode | When | Sprint workflow (`euro-ingest-loop.yml`) | Maintenance workflow |
|------|------|------------------------------------------|----------------------|
| `sprint` | any of unmeasured / zero-body / thin / `indexed_without_body` > 0 | ≤4×/day, 24 targets | off |
| `maintenance` | FTSE quality bar met (all four zero) | off (skipped) | ≤4×/day, 62 targets + discovery scan via `library-ingest-maintenance.yml` |

Phase 3 readiness is **informational only** — weekday ladder crons stay enabled during maintenance.

**Sprint UTC slots** (`euro-ingest-loop.yml`): Mon–Sat **07:15 / 10:15**; daily (incl. Sunday) **13:15 / 16:15**. Sunday morning is skipped so the quiet bundle (orchestrator ~06:20 → backup ~12:30) is not contended.
**Parallel sprint 1** (`library-ingest-sprint.yml`): same days, **+30 min** (07:45 / 10:45 / 13:45 / 16:45).
**Parallel sprint 2** (`library-ingest-sprint-2.yml`): same days, **+60 min** (08:15 / 11:15 / 14:15 / 17:15).
**Maintenance** (`library-ingest-maintenance.yml`): Mon–Sat **07:30 / 10:30**; daily **13:30 / 16:30**. Same deepen volume as live FTSE (`max_targets=62`, `max_bodies=40`).

When focus reaches parity, `ingest_parity_markets` is updated and focus may advance to
`market_queue[0]` when `focus_graduation.advance_focus_on_ingest_parity` is true.

**Parallel sprint:** `ingest_parallel_sprint` (default `["sp500"]`) and `ingest_parallel_sprint_2`
(default `["asx200"]`) front-start filing deepen on queue markets while focus is still in
sprint. When a parallel market reaches filing parity, `advance_parallel_sprint_on_ingest_parity`
(default true) removes it from its stream and promotes the next `market_queue` market that
still has gaps into the same slot. Stream 1 slots match euro focus (+30 min) via
`library-ingest-sprint.yml`; stream 2 (+60 min) via `library-ingest-sprint-2.yml`. Learning
Learning **weekly paper** (`weekly_paper_shard_markets`, capacity 1) stays on
`euro_depth` until handoff. Sunday screen-lite + observe sim follow the
**ingest profile** (focus + both sprint streams + ingest-parity +
`ftse_equivalent_markets`), so `sp500` and `asx200` keep a dated archive clock
without taking the weekly-paper slot.

`ingest_parity_met` is the FTSE quality bar for **every** library market
(unmeasured, zero-body, thin, and `indexed_without_body` all zero).
`sp500` is also in `ftse_equivalent_markets`: coverage is **canonical-only** (do not
count nasdaq100 overlap). Until `ftse-library learning-depth --market sp500` is
green, the sprint must keep seeing those real gaps (24 targets) — do **not** add
`sp500` to `ingest_parity_markets`.
Keep Sunday screen-lite so unique days / span reach 12 weeks; do not ingest all 503
constituents.

The gate runs at the start of `euro-ingest-loop.yml`, after each ingest loop, and after
library ladder when `euro_depth` is in the phase rollup. With `CRONJOB_API_KEY` in GitHub
secrets, the workflow also calls `scripts/sync_euro_ingest_cron.py` to toggle cron-job.org
jobs automatically.

### Register euro ingest crons after cadence changes

```bash
WORKFLOW_DISPATCH_PAT=… CRONJOB_API_KEY=… ./scripts/import_cron_jobs.py --all
```

Or only the euro ingest slots:

```bash
WORKFLOW_DISPATCH_PAT=… CRONJOB_API_KEY=… ./scripts/import_cron_jobs.py \
  --job euro-ingest-loop-morning \
  --job euro-ingest-loop-afternoon \
  --job euro-ingest-loop-midafternoon \
  --job euro-ingest-loop-evening \
  --job library-ingest-sprint-morning \
  --job library-ingest-sprint-afternoon \
  --job library-ingest-sprint-midafternoon \
  --job library-ingest-sprint-evening \
  --job library-ingest-sprint-2-morning \
  --job library-ingest-sprint-2-afternoon \
  --job library-ingest-sprint-2-midafternoon \
  --job library-ingest-sprint-2-evening \
  --job library-ingest-maintenance \
  --job library-ingest-maintenance-afternoon \
  --job library-ingest-maintenance-midafternoon \
  --job library-ingest-maintenance-evening \
  --disable-legacy-ingest
```

Job keys: `euro-ingest-loop-morning|afternoon|midafternoon|evening`,
`library-ingest-sprint-*`, `library-ingest-sprint-2-*`, `library-ingest-maintenance` /
`library-ingest-maintenance-afternoon|midafternoon|evening`,
`orchestrator-ladder-weekday`.

After merge of a cadence change, re-import so cron-job.org picks up Mon–Sat peak + daily
off-peak schedules and disables old weekday-only titles. GitHub `schedule` alone is best-effort.

### Filing sources (euro_filings)

1. **ESEF direct** — `filings.xbrl.org` API (`esef_direct`); country-hinted entity search + periphery aliases
2. **Google News** — euro exchange site clauses (existing)
3. **IR allowlist** — `docs/data/research_ir_urls.json` + builtin seeds for thin/unmeasured/iwb names
4. **SEC 20-F** — dual-listed names (existing)

### Critical-path monitoring (automated)

Each `ftse-library ingest-loop` run assesses buy-tier gaps and persists
`docs/data/library/ingest_critical_path.json` (+ per-market copy):

| Blocker | Automated action |
|---------|------------------|
| `unmeasured` / `thin_need_discovery` | Force listing-only `discovery_scan` even in sprint |
| `indexed_without_body` | Prefer those tickers over discovery-only thin / maintain |
| any gap | Skip high-conviction **maintain** names (no wasted slots) |
| stall / 0-improve complete batch | Auto-dispatch pinned intensive gap-closure (`stall_slowdown`) |

Inspect with the latest loop summary (`markets/<id>/ingest_summary.json` → `critical_path`).

## 30-day calendar (target)

```text
Days 1–2     Burst grow all constituents; warm-start euro_stoxx50 buy-tier ingest
Days 2–7     Daily ladder (screen archives) + 4× weekday ingest-loop (24 targets)
Days 5–12    Phase 1 gate (4 archives) → weekly shard batches (4 Sundays or daily shard-paper)
Days 12–20   Phase 2 gate + weekday shard batches (8 trading days)
Days 20–30   Phase 3 gate; monthly parity review; re-enable AI beat-rules if bodies look FTSE-like
```

## Manual burst commands

```bash
# Day 1 — full universe metrics
ftse-library grow --market euro_depth --max-tickers 200

# Filing deepen (local or workflow_dispatch)
ftse-library ingest-loop --market euro_depth --max-targets 24
gh workflow run euro-ingest-loop.yml -f market=euro_depth -f max_targets=24 -f force=true

# Accelerated ladder (screen archives without waiting for Sunday)
gh workflow run automation-orchestrator.yml -f suite=ladder_only -f force=true

# Phase 2 / 3 paper shards (when gates allow)
ftse-library shard-paper --markets euro_depth
ftse-library shard-weekday --markets euro_depth

# Status
ftse-library shard-status --markets euro_depth --json
```

## Revert after sprint

Restore conservative gates in `policy.json`:

- `phase1_min_screen_archives`: 12
- `phase2_min_weekly_batches`: 8
- `phase3_min_exit_shadow_closed`: 15
- `weekday_paper_shard_after_weekly`: false (until parity review passes)
- `focus_grow_cap`: 25
