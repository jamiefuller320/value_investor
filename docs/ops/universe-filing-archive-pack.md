# Universe-wide filing archive / data-pack lane (cold store)

**Status:** Isolation + miss-rate observe + fail-open hydrate **scaffolds shipped**;
archive **engine / crawler still parked**. Do **not** add a second live crawler or
a fourth equal sprint stream.
**Deferred:** **L499** (engine gate). Design landed via [#904](https://github.com/jamiefuller320/value_investor/pull/904).
**Source:** [Project conversation](https://cursor.com/agents/bc-01a0d034-3cd4-71bc-88ad-5088afa3424a)

## Learning question

When names rotate into buy-tier, what is the **miss rate** of first-memo / body-lag because no prior archive bodies existed — vs buy-tier-only deepen catching up in time?

## Idea (user)

A separate archival engine (possibly a separate repo) that:

1. Collates filings for **all** admitted-universe stocks as they appear (not only buy-tier deepen).
2. Serves a **data pack** when a name rotates toward buy.
3. Uses compression / the smallest accessible format for filings.

## Judgment

| Decision | Rationale |
|----------|-----------|
| Useful as **cold archive later**, not a second live ingest now | Must not compete with euro fat-slot / P2 focus head (`euro_depth` or successor) |
| Prefer **offline lane in-repo** before a separate repo | Non-interfering collation; separate repo only if size/ops evidence demands it |
| Prefer **raw originals + zstd + normalized text** first | Proprietary compact format only after size/retrieval evidence |
| Gate engine on miss-rate evidence + isolation | Isolation / quiet-window / fail-open hydrate scaffolds may ship **without** stealing the fat slot; the **crawler / pack writer** waits for maintenance threshold |

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
| Runner conflict | Quiet post-close / weekend slots, preemptible, max-concurrency 1, auto-suspend when focus is warn/stuck |
| Source conflict | **Separate identity/budget** + incremental as-published polls (not full-universe crawls) |
| Eng surface | Keep thin (poll → fetch → normalize → zstd → cold store); no scoring/memos/daily-hub |
| Completeness | Archive is **best-effort accelerator**. On hydrate, use pack if present; gaps fall through to live deepen. Never block active regime on pack holes |

## Shipped scaffolds (no crawler)

| Piece | Module / artifact | Role |
|-------|-------------------|------|
| Isolation firewall + quiet window | `universe_filing_archive_isolation.py` → `archive_lane_gate` | Separate budget IDs, preemptible, focus-pressure auto-suspend, quiet-window preference |
| Miss-rate observe | `universe_filing_archive_miss_rate.py` → `docs/data/universe_filing_archive_miss_rate.json` | Flip-lag proxy: enter without key bodies ≈ archive miss |
| Fail-open hydrate | `universe_filing_archive_hydrate.py` → `try_hydrate_pack` | Pack hit accelerates; miss/error always continues live deepen |
| Ops wiring | `check_universe_filing_archive_miss_rate` in ops-monitor; L460 optional commit; observe-utilization card | Full automation bar for the observe instrument |
| CLI drill-down | `ftse-ingest-audit --archive-miss-rate` | Ad-hoc only |

`archive_lane_gate` is **fail-closed** while the focus fat slot is in sprint (`mode=sprint` and `ingest_sprint_complete=false`) or focus has unmeasured/zero-body pressure — so these scaffolds cannot steal the euro fat slot even if a future poller is wired carelessly.

## Explicit non-goals (still)

- Second live crawler parallel to `euro-ingest-loop` / sprint streams.
- Proprietary binary filing format as v1.
- Forking shard AI-judgment or live-path utilization work to “fill the archive.”
- Fourth equal sprint stream / weekend full-universe crawl.

## Still parked (euro graduation)

| Item | Gate |
|------|------|
| Cold-store writers / pack assemble loop | Focus head at `sprint_ingest_complete` **and** isolation gate allows |
| Preemptible archive workflow | Same + separate runner labels |
| Separate-repo packaging | Only if size/ops evidence demands it |
| Promoting miss-rate → eng spray | Never from observe alone |

## Revisit trigger (engine)

Focus ingest head (`euro_depth` or successor) at **maintenance threshold** (`sprint_ingest_complete`) **and** `docs/data/universe_filing_archive_miss_rate.json` shows material enter-without-bodies — **before** proposing a second live crawler or separate archive repo.
