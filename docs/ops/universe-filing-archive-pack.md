# Universe-wide filing archive / data-pack lane (cold store)

**Status:** Isolation + miss-rate observe + fail-open hydrate scaffolds shipped; **gated
dry pack lane runnable** (week-first plan + bottleneck review). Archive
**writers still parked** pending a thin quiet-window pilot (euro fat released
2026-10-01). Do **not** add a second live crawler or a fourth equal sprint stream.
**Deferred:** **L499** (thin writer pilot); **N180** (live crawler / fourth stream);
**N181** (eng self-improve authority).
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
| Useful as **cold archive**, not a second live ingest | Must not compete with euro fat-slot / P2 focus head (`euro_depth` or successor) while fat is active; once fat is released, quiet offline collection is in-scope |
| Prefer **offline lane in-repo** before a separate repo | Non-interfering collation; separate repo only if size/ops evidence demands it |
| Prefer **raw originals + zstd + normalized text** first | Proprietary compact format only after size/retrieval evidence |
| **Do not** gate writers on miss-rate ≥50% | Collect-while-easy: elevated miss-rate means it is already too late for those flips; keep miss-rate observe-only |
| Gate writers on isolation + fat release + thin pilot | Quiet window, `archive_lane_gate`, separate budgets, no fourth equal sprint (**N180**), no eng-spray (**N181**) |

### Conditional benefit

**Would it help if it could run without impacting higher priority?** Yes — when hard isolation holds:

- Separate per-source rate-limit budgets (critical-path never shares quota with archive)
- Preemptible / separate runner class (never delay fat-slot, ingest-loop, or gap-closure)
- Cold storage off the live publish path
- Auto-suspend when focus has unmeasured/zero-body stalls, 429s, or timeout pressure

Best-effort “low priority” without those controls is not sufficient.

### Quiet window + incremental + fail-open

| Concern | Practical answer |
|---------|------------------|
| Runner conflict | Quiet band **21:00–05:00 UTC** weekdays + weekends; primary cron **Mon–Fri 22:00 UTC**; preemptible `cancel-in-progress`; max-concurrency 1; auto-suspend when focus is warn/stuck / fat sprint |
| Source conflict | **Separate identity/budget** + incremental as-published polls (not full-universe crawls) |
| Eng surface | Keep thin (poll → fetch → normalize → zstd → cold store); no scoring/memos/daily-hub |
| Completeness | Archive is **best-effort accelerator**. On hydrate, use pack if present; gaps fall through to live deepen. Never block active regime on pack holes |

## Pack assemble order (pinned — archive only)

**Week-first coverage, then iterative backward looks** — separate from the live fat/spare cascade:

1. Current ISO week × all admitted markets (+ live `ftse350`) — broad surface first.
2. Then week−1, week−2, … for the lookback window (default 12).

Module: `universe_filing_archive_pack_order.py` (`PACK_ORDER_ID=week_first_then_backward`).
This order must **not** drive `euro-ingest-loop` / sprint streams.

## Runnable gated lane (dry today)

| Piece | Role |
|-------|------|
| Workflow | `.github/workflows/universe-filing-archive-pack.yml` — cron `0 22 * * 1-5` |
| Gate | `archive_lane_gate` — suspend on focus fat / stuck; `quiet_only` outside band; fail-open exit 0 |
| Runner | `ftse-universe-archive-pack` → `run_universe_filing_archive_pack` |
| Last run | `docs/data/universe_filing_archive_pack_run.json` |
| Bottleneck review | `docs/data/universe_filing_archive_bottleneck_review.json` (post-run timings / throughput / errors by stage·market·source) |
| Ops-monitor | `check_universe_filing_archive_pack_bottleneck` — stale review warn; suspend outcomes do **not** warn |

While `mode=sprint` ∧ ¬`ingest_sprint_complete` (euro fat today), the 22:00 UTC job **runs and no-ops** with `outcome=suspend`, still refreshing the bottleneck review so the observe instrument stays fresh.

Writers / real fetches remain parked — dry assemble records the week-first plan only.

## Shipped scaffolds

| Piece | Module / artifact | Role |
|-------|-------------------|------|
| Isolation firewall + quiet window | `universe_filing_archive_isolation.py` → `archive_lane_gate` | Separate budget IDs, preemptible, focus-pressure auto-suspend, quiet-window preference |
| Week-first pack order | `universe_filing_archive_pack_order.py` | Archive-only coverage order |
| Gated dry pack run | `universe_filing_archive_pack_run.py` + workflow | Gate → plan → dry assemble → bottleneck review |
| Miss-rate observe | `universe_filing_archive_miss_rate.py` → `docs/data/universe_filing_archive_miss_rate.json` | Outcome proxy only — **not** a writer start gate |
| Fail-open hydrate | `universe_filing_archive_hydrate.py` → `try_hydrate_pack` | Pack hit accelerates; miss/error always continues live deepen |
| Ops wiring | miss-rate + bottleneck checks in ops-monitor; L460 optional commit for miss-rate; observe-utilization card for miss-rate | Full automation bar for observe instruments |
| CLI drill-down | `ftse-ingest-audit --archive-miss-rate`; `ftse-universe-archive-pack` | Ad-hoc only |

## Explicit non-goals (still)

- Second live crawler parallel to `euro-ingest-loop` / sprint streams (**N180**).
- Proprietary binary filing format as v1.
- Forking shard AI-judgment or live-path utilization work to “fill the archive.”
- Fourth equal sprint stream / weekend full-universe crawl.
- Auto-rewriting live deepen from bottleneck / miss-rate (observe/report first; **N181**).
- Waiting for miss-rate ≥50% before cold-store collection.

## Gates for cold-store writers (real fetches)

| Required | Role |
|----------|------|
| Focus fat released (`sprint_ingest_complete`) | No steal of P2 fat slot — **met** for `euro_depth` as of 2026-10-01 |
| `archive_lane_gate` allow | Quiet band + no focus-pressure suspend |
| Capacity isolation | Separate source budgets; preemptible; max-concurrency 1; no shared-quota collision with maintenance/spares |
| Thin writer pilot | Implement quiet poll→fetch→normalize→zstd path; tiny `max_units` first |
| **N180** | No second live crawler / fourth equal sprint stream |
| **N181** | No eng-spray / self-improve authority from archive findings |

Miss-rate observe stays wired for learning / dashboard attention — it does **not** block or unlock writers.

## Revisit trigger (engine / writers)

Focus ingest head at **maintenance threshold** (`sprint_ingest_complete`) **and**
`archive_lane_gate` allows (quiet, no focus pressure) **and** a thin writer pilot
is ready under separate budgets — **then** unpark quiet cold-store fetches.
Do **not** wait for elevated miss-rate. Keep **N180** (live crawler / fourth stream)
and **N181** (eng self-improve) parked. Use bottleneck review trajectories to tune
pack stages after writers unpark; use miss-rate to measure whether packs helped.
