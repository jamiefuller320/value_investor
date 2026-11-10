# Universe-wide filing archive / data-pack lane (cold store)

**Status:** Isolation + miss-rate observe + fail-open hydrate + **thin quiet
`--apply` writers** shipped (week-first plan, archive budgets). **Stage-2 floor**
live (`max_units=8`, `max_http_fetches=32`; tickers/bodies still 2/1) with
**quiet-night auto-widen** up to documented stage 3 (`16`/`64`). Nightly
22:00 UTC cron (7 days) runs bounded apply under `archive_lane_gate`. Do **not** add a
second live crawler or a fourth equal sprint stream.
**Deferred:** **N180** (live crawler / fourth stream); **N181** (eng self-improve);
**L521** thin Ops status panel shipped (outcome / clash / stage ladder / next widen); full achievement metrics still later. **L499** writers resolve caps from committed `stage_ladder`.
**Source:** [Project conversation](https://cursor.com/agents/bc-01a0d034-3cd4-71bc-88ad-5088afa3424a)

## Learning question

When names rotate into buy-tier, what is the **miss rate** of first-memo / body-lag because no prior archive bodies existed — vs buy-tier-only deepen catching up in time?

Miss-rate is an **outcome / observe instrument** for that question — **not** a start
gate for cold-store collection. Waiting for live-path miss-rate to degrade before
archiving runs counter to collect-while-easy / week-first cold store.

## Idea (user)

A separate archival engine (possibly a separate repo) that:

1. Collates filings for **all** admitted-universe stocks as they appear (not only buy-tier deepen).
2. Serves a **data pack** when a name rotates toward buy.
3. Uses compression / the smallest accessible format for filings.

## Judgment

| Decision | Rationale |
|----------|-----------|
| Useful as **cold archive**, not a second live ingest | Separate budgets and a preemptible runner so the lane does not delay the priority slot. `head_needs_fat_slot` sizes that slot; it does not suspend this lane |
| Prefer **offline lane in-repo** before a separate repo | Non-interfering collation; separate repo only if size/ops evidence demands it |
| Prefer **raw originals + zstd + normalized text** first | Proprietary compact format only after size/retrieval evidence |
| **Do not** gate writers on miss-rate ≥50% | Collect-while-easy: elevated miss-rate means it is already too late for those flips; keep miss-rate observe-only |
| Gate writers on isolation + quiet window + thin pilot | `archive_lane_gate`, separate budgets, no fourth equal sprint (**N180**), no eng-spray (**N181**). The priority slot is not a writer gate |

### Conditional benefit

**Would it help if it could run without impacting higher priority?** Yes — when hard isolation holds:

- Separate per-source rate-limit budgets (critical-path never shares quota with archive)
- Preemptible / separate runner class (never delay the priority slot, ingest-loop, or gap-closure)
- Cold storage off the live publish path
- Auto-suspend when focus has unmeasured/zero-body stalls, 429s, or timeout pressure

Best-effort “low priority” without those controls is not sufficient.

### Quiet window + incremental + fail-open

| Concern | Practical answer |
|---------|------------------|
| Runner conflict | Quiet band **21:00–05:00 UTC** weekdays + weekends; primary cron **daily 22:00 UTC** (`0 22 * * *`); preemptible `cancel-in-progress`; max-concurrency 1; auto-suspend on unmeasured/zero-body counts and stuck flags. `head_needs_fat_slot` does not suspend. No other workflow owns 22:00 UTC (Sat ingest-loop is 20:05 / 23:05) |
| Source conflict | **Separate identity/budget** + incremental as-published polls (not full-universe crawls) |
| Eng surface | Keep thin (poll → fetch → normalize → zstd → cold store); no scoring/memos/daily-hub |
| Completeness | Archive is **best-effort accelerator**. On hydrate, use pack if present; gaps fall through to live deepen. Never block active regime on pack holes |

## Pack assemble order (pinned — archive only)

**Week-first coverage, then iterative backward looks** — separate from the live fat/spare cascade:

1. Current ISO week × all admitted markets (+ live `ftse350`) — broad surface first.
2. Then week−1, week−2, … for the lookback window (default 12).

Module: `universe_filing_archive_pack_order.py` (`PACK_ORDER_ID=week_first_then_backward`).
This order must **not** drive `euro-ingest-loop` / sprint streams.

## Runnable gated lane (thin apply)

| Piece | Role |
|-------|------|
| Workflow | `.github/workflows/universe-filing-archive-pack.yml` — cron `0 22 * * *` |
| Gate | `archive_lane_gate` — suspend on unmeasured/zero-body and stuck flags; `quiet_only` outside band; `head_needs_fat_slot` does not suspend; fail-open exit 0 |
| Runner | `ftse-universe-archive-pack --apply` (caps from committed `stage_ladder`; optional `--max-units` / `--max-http-fetches` overrides) |
| Writers | `universe_filing_archive_writer` → cold root `docs/data/archive/universe_filings/` (gitignored) |
| Last run | `docs/data/universe_filing_archive_pack_run.json` (includes `capacity_isolation`, capped `unit_results`, `unit_status_counts`) |
| Bottleneck review | `docs/data/universe_filing_archive_bottleneck_review.json` (`by_market` attempted/completed from unit results) |
| Status panel | `docs/data/universe_filing_archive_status.json` — thin Ops card (outcome, clash flags, `stage_ladder` streak/stage, next widen); Automation → Ops |
| Ops-monitor | `check_universe_filing_archive_pack_bottleneck` + `check_universe_filing_archive_auto_widen` — stale review warn; info when auto-widen fires; suspend outcomes do **not** warn; refreshes status panel |

The 22:00 UTC job runs under `archive_lane_gate`. `head_needs_fat_slot` and a sprint-mode dispatch do not no-op it. A quiet-window miss, the archive’s own caps, or remaining focus pressure (unmeasured, zero-body, stuck flags) still no-ops with `outcome=suspend` or `quiet_only`, and still refreshes the bottleneck review.

Apply caps resolve from committed `stage_ladder` (floor stage 2 = 8/32; ceiling stage 3 = 16/64): ≤2 tickers/unit, ≤1 body/ticker, archive budget IDs only (`universe_filing_archive:*`), preemptible, `fourth_equal_sprint_stream=false`. Ladder: pilot 2/8 → stage 1 4/16 → stage 2 8/32 → stage 3 16/64.

## Shipped scaffolds

| Piece | Module / artifact | Role |
|-------|-------------------|------|
| Isolation firewall + quiet window | `universe_filing_archive_isolation.py` → `archive_lane_gate` | Separate budget IDs, preemptible, focus-pressure auto-suspend, quiet-window preference |
| Week-first pack order | `universe_filing_archive_pack_order.py` | Archive-only coverage order |
| Gated pack run | `universe_filing_archive_pack_run.py` + workflow | Gate → plan → dry or thin apply → bottleneck review |
| Thin writers | `universe_filing_archive_writer.py` | Bounded fetch + cold `pack_index` / raw / normalized |
| Miss-rate observe | `universe_filing_archive_miss_rate.py` → `docs/data/universe_filing_archive_miss_rate.json` | Outcome proxy only — **not** a writer start gate |
| Fail-open hydrate | `universe_filing_archive_hydrate.py` → `try_hydrate_pack` | Pack hit accelerates; miss/error always continues live deepen |
| Stage ladder + quiet streak | `universe_filing_archive_stage.py` → status `stage_ladder` | Auto-promote one documented stage after 5 clean nights; hard ceiling stage 3; fail-closed streak reset |
| Ops wiring | miss-rate + bottleneck + auto-widen checks in ops-monitor; L460 optional commit for miss-rate; observe-utilization card for miss-rate | Full automation bar for observe instruments |
| CLI drill-down | `ftse-ingest-audit --archive-miss-rate`; `ftse-universe-archive-pack` | Ad-hoc only |

## Explicit non-goals (still)

- Second live crawler parallel to `euro-ingest-loop` / sprint streams (**N180**).
- Proprietary binary filing format as v1.
- Forking shard AI-judgment or P1 Investment-demanded work to “fill the archive.”
- Fourth equal sprint stream / weekend full-universe crawl.
- Auto-rewriting live deepen from bottleneck / miss-rate (observe/report first; **N181**).
- Waiting for miss-rate ≥50% before cold-store collection.

## Gates for cold-store writers (real fetches)

| Required | Role |
|----------|------|
| Priority slot does not pause this lane | `head_needs_fat_slot` (and the legacy `mode=sprint` stand-in) is not an `archive_lane_gate` suspend. The slot still sizes the ingest head |
| `archive_lane_gate` allow | Quiet band + no unmeasured, zero-body, or stuck-flag suspend |
| Capacity isolation | Archive budget IDs + hard HTTP fetch cap; recorded on each `pack_run` as `capacity_isolation` |
| Thin writer pilot → stage 2 | **Shipped** — quiet apply; stage-2 caps 8/32 |
| **N180** | No second live crawler / fourth equal sprint stream |
| **N181** | No eng-spray / self-improve authority from archive findings |

Miss-rate observe stays wired for learning / dashboard attention — it does **not** block or unlock writers.

## Scale / revisit

**Stage 2 floor** (owner volume raise 2026-11-10; stage-1→2 gate met — ≥5 quiet
`isolation_ok` apply nights at 4/16): `max_units=8`, `max_http_fetches=32`.

**Quiet-night auto-widen (shipped):** after **5** consecutive clean
`apply_complete` nights with `capacity_isolation.isolation_ok=true` and no shared
429 / runner collision / fourth-sprint flag (weekend applies count), promote
**one** documented stage and reset the streak. Hard ceiling = **stage 3**
(`max_units=16`, `max_http_fetches=64`) — do not invent stages past the ladder.
Suspend / isolation fail / shared-path / apply errors **fail-closed** (streak → 0);
they do not auto-rollback the committed stage (manual rollback still available).
State lives on `docs/data/universe_filing_archive_status.json` → `stage_ladder`.
Ops-monitor emits info **Cold-store archive pack auto-widened** when a promote
fires (`auto_fixable=false`). Keep **N180** / **N181** parked. Use bottleneck
review to tune stages; use miss-rate to measure whether packs helped (observe only).
