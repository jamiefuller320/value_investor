# Universe-wide filing archive / data-pack lane (cold store)

**Status:** Isolation + miss-rate observe + fail-open hydrate + **thin quiet
`--apply` writers** shipped (week-first plan, archive budgets). **Stage-1 caps**
live: `max_units=4`, `max_http_fetches=16` (tickers/bodies still 2/1). Weekday
22:00 UTC cron runs bounded apply under `archive_lane_gate`. Do **not** add a
second live crawler or a fourth equal sprint stream.
**Deferred:** **N180** (live crawler / fourth stream); **N181** (eng self-improve);
**L521** thin Ops status panel shipped (outcome / clash / next widen); full achievement metrics still later. **L499** writers on stage-1 thin widen — accumulate quiet isolation_ok nights before stage 2.
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
| Runner conflict | Quiet band **21:00–05:00 UTC** weekdays + weekends; primary cron **Mon–Fri 22:00 UTC**; preemptible `cancel-in-progress`; max-concurrency 1; auto-suspend on unmeasured/zero-body counts and stuck flags. `head_needs_fat_slot` does not suspend |
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
| Workflow | `.github/workflows/universe-filing-archive-pack.yml` — cron `0 22 * * 1-5` |
| Gate | `archive_lane_gate` — suspend on unmeasured/zero-body and stuck flags; `quiet_only` outside band; `head_needs_fat_slot` does not suspend; fail-open exit 0 |
| Runner | `ftse-universe-archive-pack --apply --max-units 4 --max-http-fetches 16` |
| Writers | `universe_filing_archive_writer` → cold root `docs/data/archive/universe_filings/` (gitignored) |
| Last run | `docs/data/universe_filing_archive_pack_run.json` (includes `capacity_isolation`) |
| Bottleneck review | `docs/data/universe_filing_archive_bottleneck_review.json` |
| Status panel | `docs/data/universe_filing_archive_status.json` — thin Ops card (outcome, clash flags, next widen); Automation → Ops |
| Ops-monitor | `check_universe_filing_archive_pack_bottleneck` — stale review warn; suspend outcomes do **not** warn; refreshes status panel |

The 22:00 UTC job runs under `archive_lane_gate`. `head_needs_fat_slot` and a sprint-mode dispatch do not no-op it. A quiet-window miss, the archive’s own caps, or remaining focus pressure (unmeasured, zero-body, stuck flags) still no-ops with `outcome=suspend` or `quiet_only`, and still refreshes the bottleneck review.

Apply caps (stage 1): `max_units=4`, ≤2 tickers/unit, ≤1 body/ticker, ≤16 HTTP fetches/run, archive budget IDs only (`universe_filing_archive:*`), preemptible, `fourth_equal_sprint_stream=false`. Prior pilot was 2/8.

## Shipped scaffolds

| Piece | Module / artifact | Role |
|-------|-------------------|------|
| Isolation firewall + quiet window | `universe_filing_archive_isolation.py` → `archive_lane_gate` | Separate budget IDs, preemptible, focus-pressure auto-suspend, quiet-window preference |
| Week-first pack order | `universe_filing_archive_pack_order.py` | Archive-only coverage order |
| Gated pack run | `universe_filing_archive_pack_run.py` + workflow | Gate → plan → dry or thin apply → bottleneck review |
| Thin writers | `universe_filing_archive_writer.py` | Bounded fetch + cold `pack_index` / raw / normalized |
| Miss-rate observe | `universe_filing_archive_miss_rate.py` → `docs/data/universe_filing_archive_miss_rate.json` | Outcome proxy only — **not** a writer start gate |
| Fail-open hydrate | `universe_filing_archive_hydrate.py` → `try_hydrate_pack` | Pack hit accelerates; miss/error always continues live deepen |
| Ops wiring | miss-rate + bottleneck checks in ops-monitor; L460 optional commit for miss-rate; observe-utilization card for miss-rate | Full automation bar for observe instruments |
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
| Thin writer pilot → stage 1 | **Shipped** — quiet apply; stage-1 caps 4/16 |
| **N180** | No second live crawler / fourth equal sprint stream |
| **N181** | No eng-spray / self-improve authority from archive findings |

Miss-rate observe stays wired for learning / dashboard attention — it does **not** block or unlock writers.

## Scale / revisit

**Stage 1 applied** (owner lock): `max_units=4`, `max_http_fetches=16`. Never
auto-widen — human/eng raises workflow + code defaults only.

Before **stage 2** (`max_units=8`, `max_http_fetches=32`): accumulate **5** quiet
weekday apply nights with `capacity_isolation.isolation_ok=true` and no shared
429 / runner collision vs euro maintenance or spare sprints. Rollback to prior
stage (or pilot 2/8) on isolation fail, shared critical path, or focus-pressure
suspend churn. Keep **N180** / **N181** parked. Use bottleneck review to tune
stages; use miss-rate to measure whether packs helped (observe only).
