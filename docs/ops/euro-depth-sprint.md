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
| Filing deepen (buy-tier) | `ftse-library ingest-loop --market euro_depth` | Weekdays: **euro-ingest-loop.yml** 4×/day sprint on focus; **library-ingest-sprint.yml** 4×/day on `ingest_parallel_sprint` (sp500); **library-ingest-maintenance.yml** daily once parity met |
| Screen + observe + weekly shard | `ftse-library ladder` | Daily `ladder_only` when eng idle + Sundays |
| Phase 3 weekday shard | `ftse-library shard-weekday --markets euro_depth` | Weekdays after Phase 2 gate |

### Completion gate (ingest throttle)

`ftse-library euro-ingest-dispatch` evaluates **buy-tier filing parity** on the focus market
and persists `docs/data/library/euro_ingest_dispatch.json`:

| Mode | When | Sprint workflow (`euro-ingest-loop.yml`) | Maintenance workflow |
|------|------|------------------------------------------|----------------------|
| `sprint` | `unmeasured + zero_body > 0` | 4×/day, 24 targets | off |
| `maintenance` | filing parity met | off (skipped) | 1×/day, 4 targets + discovery scan via `library-ingest-maintenance.yml` |

Phase 3 readiness is **informational only** — weekday ladder crons stay enabled during maintenance.

Sprint UTC slots: **07:15 / 10:15 / 13:15 / 16:15** (≈96 ticker-slots/weekday).
Maintenance UTC slot: **07:30** weekdays (`library-ingest-maintenance.yml`).

When focus reaches parity, `ingest_parity_markets` is updated and focus may advance to
`market_queue[0]` when `focus_graduation.advance_focus_on_ingest_parity` is true.

**Parallel sprint:** `ingest_parallel_sprint` (default `["sp500"]`) front-starts filing
deepen on the next queue market while focus is still in sprint. Slots: **07:45 / 10:45 /
13:45 / 16:45** UTC via `library-ingest-sprint.yml` (30 minutes after euro focus slots).
Learning focus (`weekly_paper_shard_markets`, observe sim) stays on `euro_depth` until handoff.

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
  --job euro-ingest-loop-evening
```

Job keys: `euro-ingest-loop-morning`, `euro-ingest-loop-afternoon`,
`euro-ingest-loop-midafternoon`, `euro-ingest-loop-evening`,
`orchestrator-ladder-weekday`.

After merge of a cadence change, re-import so cron-job.org picks up new slots and
`max_targets=24` dispatch bodies (GitHub `schedule` alone is best-effort).

### Filing sources (euro_filings)

1. **ESEF direct** — `filings.xbrl.org` API (`esef_direct`)
2. **Google News** — euro exchange site clauses (existing)
3. **IR allowlist** — `docs/data/research_ir_urls.json`
4. **SEC 20-F** — dual-listed names (existing)

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
