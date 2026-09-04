# Library ingest escalation (FTSE parity)

Reusable weekday filing-deepen escalation for **offline library markets**. The
`euro_depth` sprint is the first pilot; `sp500` is the first
**FTSE-equivalent** market (`policy.ftse_equivalent_markets`). Copy this pattern
when adding the next market shard (e.g. `asx200` offline depth).

Live FTSE reference: [`ingest-loop.yml`](../../.github/workflows/ingest-loop.yml),
[`docs/ops/horizon-scan.md`](horizon-scan.md) (gap-closure runs).

## Cascade model

```text
Stage 0 — Live FTSE 350
  ingest-loop.yml → ingest_health_log → stall → micro-compile ingest tasks
  gap-closure runs → eng queue → verify merged → ingest-loop rerun

Stage 1 — Library market pilot (euro_depth)
  euro-ingest-loop.yml (sprint) + library-ingest-maintenance.yml (parity)
  → markets/{id}/ingest_health_log → stall → micro-compile
  same ingest_gap_closure_runs.json + engineering_tasks.json queue

Stage 2+ — Next library markets
  Reuse ftse-library ingest-loop --market {id} with the same escalation module
  when Phase 2/3 gates justify filing parity work
```

**Rule:** richness before breadth on the live path; library markets grow filing
depth offline using the same eng escalation semantics as FTSE.

## Artifacts (per market)

| Path | Purpose |
|------|---------|
| `docs/data/library/markets/{market_id}/ingest_health_log.json` | Before/after filing health snapshots |
| `docs/data/library/markets/{market_id}/ingest_summary.json` | Latest run targets + per-ticker results |
| `docs/data/library/markets/{market_id}/learning_depth.json` | FTSE-equivalent filing + trajectory readiness (`ftse-library learning-depth --write`) |
| `docs/data/library/markets/{market_id}/screen/trajectory_*.json` | Library trajectory artifacts (refreshed after observe-sim on FTSE-equivalent markets) |
| `docs/data/library/euro_ingest_dispatch.json` | Sprint vs maintenance gate (focus market) |
| `docs/data/library/library_ingest_discovery_scan_summary.json` | Maintenance discovery scan summary |
| `docs/data/ingest_gap_closure_runs.json` | Shared gap-closure run log (FTSE + library) |
| `docs/data/engineering_tasks.json` | Shared engineering queue |

Legacy `docs/data/library/euro_ingest_health_log.json` is still read for
`euro_depth` when the per-market log is absent.

## Escalation paths

### 1. Micro-compile on stall

After **`stall_runs`** consecutive library ingest runs (default **2**) where:

- buy-tier filing gaps (`unmeasured + zero_body`) are unchanged and &gt; 0, and
- no tickers improved in those runs,

`compile_library_ingest_engineering_tasks_micro` drafts one **ingest** task scoped
to `market_id` (`source=library_ingest_stall`).

### 2. Stall / slowdown follow-up (automatic)

After a library ingest batch that is not already a gap-closure run,
`evaluate_library_ingest_gap_closure_followup` dispatches a pinned intensive
pass when:

- ingest health is **stalled**, or
- the batch **improved 0 tickers** and buy-tier gaps remain
  (unmeasured, zero-body, or `indexed_without_body`)

Partial / `runtime_cutoff` runs still skip when listing discovery itself was
cut off or deepen never started (the discovery time cap is the fix for those).
After the cap, a cutoff deepen that already ran ≥1 ticker and improved nobody
**does** fire — that is today's euro failure mode (2/24 names, `improved=[]`,
`RAND.AS` still zero-body). It does **not** fire on a productive deepen that
still has leftover IWB. Cooldown is **6h per `market_id`** so a FTSE intensive
does not block euro (and vice versa). An open library ingest engineering task
for that market also skips the dispatch.

The follow-up is wired on **every** library ingest workflow (`euro-ingest-loop.yml`,
`library-ingest-sprint.yml`, `library-ingest-sprint-2.yml`,
`library-ingest-maintenance.yml`). Sprint/maintenance evaluate each market in
the batch JSON; dispatches still run as pinned `euro-ingest-loop.yml` jobs
(`force=true`, same intensive inputs as FTSE weekday follow-up):

```bash
gh workflow run euro-ingest-loop.yml \
  -f market=sp500 -f max_targets=1 -f max_bodies=40 \
  -f max_runtime_seconds=2100 -f force=true \
  -f record_gap_closure=true -f pin_ticker=XYZ \
  -f gap_closure_trigger=stall_slowdown
```

Candidate order uses `select_library_ingest_targets` (unmeasured / zero-body
ahead of IWB), preferring `health_after.zero_body_tickers[0]` when present.

Evaluate locally with:

```bash
ftse-library ingest-gap-closure-followup \
  --market euro_depth --loop-json /tmp/euro_ingest_loop.json --json
```

### 3. Gap-closure compile

When a run is recorded with `--record-gap-closure` (or workflow
`record_gap_closure=true`) and the pinned / top-gap ticker still fails after the
pass, `compile_ingest_engineering_task_from_trial` queues a chained ingest task
(same chain limits as FTSE, max 3 rounds).

Gap runs carry `params.market_id` and `params.universe=library` so verification
and gap detection use the market canonical filing index.

## Commands

```bash
# Weekday deepen (sprint automation)
ftse-library ingest-loop --market euro_depth --max-targets 24

# FTSE-standard maintenance (parity markets; discovery scan on by default)
ftse-library ingest-maintenance --json

# Parallel sprint (queue head-start while focus still sprinting)
ftse-library ingest-sprint --json

# Manual gap-closure pass
ftse-library ingest-loop --market euro_depth --max-targets 1 --record-gap-closure \
  --pin-ticker SHELL.AS --gap-closure-review-trigger horizon_scan

# Verification rerun after engineering merge
gh workflow run euro-ingest-loop.yml -f market=euro_depth -f record_gap_closure=true \
  -f pin_ticker=SHELL.AS -f gap_closure_parent_id=igc-YYYYMMDD-01

# Dispatch / gate status
ftse-library euro-ingest-dispatch --json
```

## Workflow hooks (FTSE parity)

| Hook | Workflow | Behaviour |
|------|----------|-----------|
| Sprint ingest (focus) | `euro-ingest-loop.yml` | Runs only when focus `should_run_sprint_ingest` |
| Sprint ingest (parallel 1) | `library-ingest-sprint.yml` | Runs `ingest_parallel_sprint` markets with gaps (e.g. sp500) |
| Sprint ingest (parallel 2) | `library-ingest-sprint-2.yml` | Runs `ingest_parallel_sprint_2` markets with gaps (e.g. asx200); auto-advances queue on parity |

Parallel sprint auto-advance (`advance_parallel_sprint_on_ingest_parity`, default true) rotates
`market_queue` markets through stream slots when filing parity is met. FTSE-equivalent markets
(`ftse_equivalent_markets`, e.g. sp500) still defer `ingest_parity_markets` / maintenance until
`learning-depth` is green; non-equivalent markets (euro_depth, asx200) use the same
`ingest_parity_met` bar and enter maintenance immediately on parity.
| Maintenance ingest | `library-ingest-maintenance.yml` | 2×/weekday FTSE-standard scan-then-target (`max_targets=62`) for markets at the FTSE quality bar |
| Stall / slowdown follow-up | all library ingest workflows | After stall or `improved=0` leftover gaps (including cutoff deepens that already ran), dispatches pinned `euro-ingest-loop.yml` (`record_gap_closure=true`, `max_targets=1`) via `scripts/dispatch_library_gap_closure_followups.sh` |
| Micro-compile dispatch | `euro-ingest-loop.yml` | After `micro_compiled` or `gap_closure_compiled`, runs `engineering-queue.yml` immediately |
| Post-merge verify rerun | `engineering-queue.yml` | Tasks with `evidence.market_id` rerun **`euro-ingest-loop.yml`**; FTSE tasks still use `ingest-loop.yml` |
| Discovery time cap | `library_ingest_budget.py` | Listing discovery may use at most 25% of `max_runtime_seconds` (675s of a 2700s euro slot) and scans thin/unmeasured/zero-body/IWB names first. Body deepen keeps the rest of the clock. |
| Clean JSON for CI | `euro-ingest-loop.yml` | Uses `ingest-loop --json-path` / `euro-ingest-dispatch --json-path` (not `tee`) so stdout warnings (e.g. PyMuPDF `fitz`) cannot break `GITHUB_OUTPUT` parsing |
| Artifact push | `scripts/push_library_ingest_artifacts.sh` | Stashes allowlisted paths (`docs/data/library/`, `engineering_tasks.json`, `ingest_gap_closure_runs.json`) before `checkout origin/main`; restores only files the job changed so concurrent queue updates are not clobbered |
| pip install retry | `scripts/gha_pip_install.sh` | 4 attempts with backoff for transient PyPI / empty-index flakes (`from versions: none`) |

A weekly **ingest director** or a second stock-by-stock deepening engine would
not fix this stall: the intensive pin already exists (`record_gap_closure` +
`compile_ingest_engineering_task_from_trial`). The miss was that follow-up
skipped every cutoff run. Revisit a director only if the intensive path still
returns 0/N after three gap-closure rounds, or we need cross-market ingest
scheduling. Per-ticker time budgets (`L131`) remain the next deepen-throughput
lever if one IR allowlist name still eats the slot.

## Filing-quality bar (all library markets)

`ingest_parity_met()` uses the **live FTSE maintenance bar** for every market:
unmeasured, zero-body, thin-body, and `indexed_without_body` must all be zero.
Maintenance then uses the same deepen volume as `ingest-loop.yml`
(`max_targets=62`, `max_bodies=40`, 2×/weekday). Do not keep a lighter library
variant — learning needs the same body quality as soon as a market is the
paper/research focus.

Policy `ftse_equivalent_markets: ["sp500"]` changes **measurement only**:

1. **Canonical-only coverage.** `_filing_coverage_for_ticker(..., canonical_only=True)`
   reads only `markets/sp500/screen/research/{TICKER}/`. Bodies that exist only under
   `nasdaq100` (or any other shard) are **unmeasured** for S&P.
2. **Health snapshot** includes `indexed_without_body`, `bodies_min` / `median` /
   `max`, `coverage_scope`, and `ftse_equivalent`.
3. **Do not** append `sp500` to `ingest_parity_markets` until
   `ftse-library learning-depth --market sp500` is green (`learning_ready`).
4. Parallel sprint then sees real canonical gaps (24 targets) instead of a
   maintenance pass that treated shard fallback as zero gaps.

```bash
ftse-library learning-depth --market sp500 --json
# expect filing_ready=false / trajectory_ready=false until depth matches FTSE
```

## Adding a new market

1. Ensure `ftse-library grow` + `screen-lite` produce a buy-tier shortlist.
2. Point `ingest-loop --market {id}` at the market (workflow or cron).
3. Confirm `markets/{id}/ingest_health_log.json` accumulates before expecting stall
   escalation (needs ≥2 runs).
4. Completion gate lives in `library_ingest_dispatch.py` (euro wrapper: `euro_depth_ingest_dispatch.py`).
5. Register cron via `scripts/import_cron_jobs.py` when the market graduates from
   manual pilot.

## Related

- [`euro-depth-sprint.md`](euro-depth-sprint.md) — sprint cadence and Phase 3 gates
- [`engineering-sync.md`](engineering-sync.md) — post-merge verify + gap-closure chain
- [`market-sharded-learning.md`](market-sharded-learning.md) — ladder / shard phases
