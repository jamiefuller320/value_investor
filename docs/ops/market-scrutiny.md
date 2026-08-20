# Market scrutiny plan (stage 2b → stage 3)

Offline scrutiny grows **Layer B screen-lite** and **Layer C selective research** on
graduated markets while the live path stays on FTSE 350. Weekday **ingest-loop**
closes live buy-tier filing gaps (no `weekly_ops` spend — filing fetches only).

Related: [`PROJECT_OBJECTIVE.md`](../PROJECT_OBJECTIVE.md), [`primary-learning-track.md`](primary-learning-track.md), [`orchestrator-cron.md`](orchestrator-cron.md).

## Current snapshot (Aug 2026)

| Lane | Status | Gap |
|------|--------|-----|
| **FTSE live ingest** | 70/70 buy-tier measured; **0 zero-body** | 13 tickers with 1–5 residual indexed-without-body (unfetchable tail) |
| **FTSE filing depth** | ~3,700 bodies; global indexed-without-body ~36 | Weekday depth continues; not a one-shot sprint |
| **Offline queue** | Breadth queue complete; **depth-first focus `euro_depth`** (~194 names) | Grow metrics + screen archives; deepen `euro_filings` on buy-tier |
| **Focus `euro_depth`** | Constituents seeded (STOXX50 ∪ periphery); research_all_graduated off | Sunday ladder concentrates weekly_ops on this book only |
| **S&P / STOXX shards** | Demoted from weekly slot under depth-first policy | Layer A maintenance only until euro_depth filing parity |
| **`weekly_ops`** | $80 cap | Sunday email + ladder selective research |
| **Director–worker** | Exploration phase (15/week); **MEGP.L** trial run 2026-08-16 | `auto_escalate_director` stays false until calibrated |

## Spend pools (what costs money)

| Work | Pool | Typical cost | Notes |
|------|------|--------------|-------|
| Weekday ingest-loop | **None** (GHA + CH API) | ~$0 Cursor | Filing index, CH/RNS/IR bodies, gap-fill deepen |
| Sunday ladder memos | `weekly_ops` | ~$0.40/memo (`composer-2.5`) | Capped by `research_hard_cap` + weekly cap |
| Sunday email agents | `weekly_ops` | ~$15–25/run | Deep analysis, gap-fill, post-run review |
| Ad-hoc depth | `ad_hoc` checkpoint | $60 default | `ftse-library ladder --unrestricted-budget` |

Raising **`weekly_ops_cap_usd`** does **not** fund ingest — it funds Sunday scrutiny memos and email agents.

## FTSE 350 — ingest volume to close gaps

### 11 unmeasured buy-tier tickers

Each needs: bootstrap filings index → ingest-improvement pass (bodies + alternate sources).

| Setting | Before | After (this plan) |
|---------|--------|-------------------|
| Ingest days | Mon / Wed / Fri | **Mon–Fri** |
| Runs per day | 2 (07:05, 10:05 UTC) | 2 (unchanged) |
| `max_targets` | 8 | **12** |
| `bootstrap_seed_cap` | 3 | **6** |

**Capacity:** 5 days × 2 runs × 12 targets = **120 ticker-slots/week**.

**Time to clear 11 unmeasured:** **1–2 ingest days** (unmeasured get +10 priority; 6 bootstrap slots per run → 2 runs cover all 11).

### 167 indexed-without-body (depth tail)

Not a single sprint — ingest prioritises zero-body and period gaps. At **120 slots/week**, expect meaningful depth improvement over **2–4 weeks** without extra Cursor spend.

### Immediate burst (optional)

From GitHub Actions → **FTSE Ingest Loop** → Run workflow:

- `max_targets`: `12`
- `force`: `true`

Run twice same UTC day (gate allows 2 successes/day) to push all 11 unmeasured in one afternoon.

```bash
gh workflow run ingest-loop.yml -f max_targets=12 -f force=true
```

## Offline markets — scrutiny volume

### Layer B screen-lite (focus market)

Requires **≥`effective_min_metrics_for_screen`** usable rows (`min(policy_min=25, ticker_count)`).
**`omxs30`** and **`iseq20`** both have honest Yahoo fetches working (``.ST`` / ``.IR`` repair + Stooq suffix map).
ISEQ 20 is only 20 names — the ladder must use the effective floor (20), not a hard 25, or screen-lite never runs.

**Resolved (Aug 2026):** Irish ``A5G-IR.L`` mangling → ``A5G.IR``; Nordic ``ABB-ST.L`` → ``ABB.ST``; Stooq ``a5g.ir`` / ``abb.st``; ladder gate uses `effective_min_metrics_for_screen`.

When metrics work: one `ftse-library ladder` Sunday pass screens focus names + observe sim if configured.

### Library grow health log + stall → engineering (latent failures)

Mirrors weekday **ingest stall** detection (`ingest_health_log.json` → `compile_ingest_engineering_task` in ops-monitor). Offline library ladder now records honest fetch health after each run:

| Artifact | Path | Purpose |
|----------|------|---------|
| Grow health log | `docs/data/library/grow_health_log.json` | Per-run focus-market snapshot: `ok_fetch_count`, `failed_fetch_count`, `usable_metrics_rows`, deltas vs previous run |
| Honest coverage | manifest `honest_coverage_count` / `library_status.json` | Counts only `fetch_status=ok` — failed refreshes no longer inflate `coverage_pct` |
| Stall compile | `library_grow_stall` via `compile_library_stall_engineering_task` | After **≥2** ladder runs with flat zero progress (failed fetches persist, usable metrics unchanged at 0), drafts a supervised `coverage` engineering task |

**Latent failure** = manifest looked complete (`coverage_count == ticker_count`) but every row failed fetch or metrics are unusable (e.g. chart-only price with no P/E). `ladder_metrics_block_assessment` tags these as `latent_fetch_failure`.

Dedup: stall compile and ladder draft both skip when an open `coverage` task already exists for the focus market.

**Eng-idle offline progression:** when the engineering queue is idle and live ingest gap-closure is not needed, `evaluate_eng_idle_offline_dispatch()` chains `automation-orchestrator suite=ladder_only` (weekdays, max 1/week via accelerated review log). Skips when fetch is stalled (engineering owns the fix).

**Post-coverage-merge verify:** when a `coverage` engineering task merges, `try-accelerated-ladder` chains `ladder_only` to re-grow and verify the fetch fix before the next Sunday.

**Tail-market grow:** `effective_focus_grow_tickers()` sweeps the full focus universe in one Sunday pass when ticker count fits the plan cap (omxs30=30, iseq20=20).

```bash
# Inspect grow health (local)
python3 -c "from value_investor.library_grow_health import snapshot_focus_market_health; import json; print(json.dumps(snapshot_focus_market_health(), indent=2))"
```

### Layer C selective research + observe sim

| Knob | Value | Effect |
|------|-------|--------|
| `weekly_ops_cap_usd` | **80** | ~$30 more headroom for Sunday bundle |
| `research_hard_cap` | **100** | Max memos per ladder run |
| `observe_sim_markets` | `sp500`, `euro_stoxx50`, `iseq20` | Per-market observe sim after screen-lite — see [`market-sharded-learning.md`](market-sharded-learning.md) |

At $0.40/memo and ~$35–45 Sunday email burn, **$80 weekly_ops** supports roughly **~40–60 selective memos/week** across graduated markets (round-robin buy-tier).

### Progression through markets

1. **FTSE ingest** — residual indexed-without-body depth (buy-tier measured).
2. **`euro_depth` metrics + screen archives** — sole offline research/observe/weekly focus.
3. **Deepen `euro_filings`** on euro_depth buy-tier before treating AI tracks as FTSE-equivalent.
4. **Keep Layer A maintenance** on other graduated markets — no stage-4 live expansion until stage **2b** shows edge vs ^FTSE.

## Commands

```bash
ftse-ingest-loop status --json
ftse-library policy                    # weekly_ops cap + ladder knobs
ftse-library ladder --dry-run-research # Sunday shortlist preview
ftse-library screen --markets iseq20   # focus screen-lite (20-name floor)
```

## Cron alignment

Re-import cron jobs after merge so external cron matches weekday ingest schedule:

```bash
CRONJOB_API_KEY=… WORKFLOW_DISPATCH_PAT=… ./scripts/import_cron_jobs.py --job ingest-loop-morning
CRONJOB_API_KEY=… WORKFLOW_DISPATCH_PAT=… ./scripts/import_cron_jobs.py --job ingest-loop-afternoon
```
