# Market scrutiny plan (stage 2b → stage 3)

Offline scrutiny grows **Layer B screen-lite** and **Layer C selective research** on
graduated markets while the live path stays on FTSE 350. Weekday **ingest-loop**
closes live buy-tier filing gaps (no `weekly_ops` spend — filing fetches only).

Related: [`PROJECT_OBJECTIVE.md`](../PROJECT_OBJECTIVE.md), [`primary-learning-track.md`](primary-learning-track.md), [`orchestrator-cron.md`](orchestrator-cron.md).

## Current snapshot (Aug 2026)

| Lane | Status | Gap |
|------|--------|-----|
| **FTSE live ingest** | 52/63 buy-tier measured; **11 unindexed** | `VSVS.L`, `INCH.L`, `BOY.L`, `GCP.L`, `BKG.L`, `PETS.L`, `KGF.L`, `DRX.L`, `BWY.L`, `PTEC.L`, `MGAM.L` |
| **FTSE filing depth** | 496 bodies; 167 indexed without body | Ongoing weekday depth (not one-shot) |
| **Focus `omxs30`** | Layer A constituents 100%; metrics fetch **stalls in CI** (Yahoo 401) | `grow_health_log.json` + engineering `coverage` task on stall |
| **S&P 500 observe sim** | Running after Sunday screen-lite | Continue weekly |
| **`weekly_ops`** | $50 cap → **$80** after this plan | Sunday email + ladder selective research |

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

Requires **≥25 tickers with usable metrics** (`min_metrics_for_screen`). **`omxs30` is blocked** until metrics refresh succeeds — constituents exist but every ticker shows Yahoo 401 / Stooq errors.

**Next engineering focus:** Swedish `.ST` metrics provider path (not more Sunday memo budget).

When metrics work: one `ftse-library ladder` Sunday pass screens 30 names + observe sim if configured.

### Library grow health log + stall → engineering (latent failures)

Mirrors weekday **ingest stall** detection (`ingest_health_log.json` → `compile_ingest_engineering_task` in ops-monitor). Offline library ladder now records honest fetch health after each run:

| Artifact | Path | Purpose |
|----------|------|---------|
| Grow health log | `docs/data/library/grow_health_log.json` | Per-run focus-market snapshot: `ok_fetch_count`, `failed_fetch_count`, `usable_metrics_rows`, deltas vs previous run |
| Honest coverage | manifest `honest_coverage_count` / `library_status.json` | Counts only `fetch_status=ok` — failed refreshes no longer inflate `coverage_pct` |
| Stall compile | `library_grow_stall` via `compile_library_stall_engineering_task` | After **≥2** ladder runs with flat zero progress (failed fetches persist, usable metrics unchanged at 0), drafts a supervised `coverage` engineering task |

**Latent failure** = manifest looked complete (`coverage_count == ticker_count`) but every row failed fetch or metrics are unusable (e.g. chart-only price with no P/E). `ladder_metrics_block_assessment` tags these as `latent_fetch_failure`.

Dedup: stall compile and ladder draft both skip when an open `coverage` task already exists for the focus market.

```bash
# Inspect grow health (local)
python3 -c "from value_investor.library_grow_health import snapshot_focus_market_health; import json; print(json.dumps(snapshot_focus_market_health(), indent=2))"
```

### Layer C selective research + observe sim

| Knob | Value | Effect |
|------|-------|--------|
| `weekly_ops_cap_usd` | **80** | ~$30 more headroom for Sunday bundle |
| `research_hard_cap` | **100** | Max memos per ladder run |
| `observe_sim_markets` | `sp500` | S&P observe sim after screen-lite |

At $0.40/memo and ~$35–45 Sunday email burn, **$80 weekly_ops** supports roughly **~40–60 selective memos/week** across graduated markets (round-robin buy-tier).

### Progression through markets

1. **FTSE ingest** — close 11 unmeasured (this week).
2. **Fix `omxs30` metrics** — engineering queue (`eng-20260810-01` or auto-drafted `library_ladder` task); then screen-lite + optional `observe_sim_markets: ["sp500", "omxs30"]`.
3. **Graduate `omxs30`** → focus advances to **`iseq20`** (queue tail).
4. **Keep S&P observe sim** accumulating — no stage-4 live expansion until stage **2b** shows edge vs ^FTSE.

## Commands

```bash
ftse-ingest-loop status --json
ftse-library policy                    # weekly_ops cap + ladder knobs
ftse-library ladder --dry-run-research # Sunday shortlist preview
ftse-library screen --markets omxs30   # after metrics fix
```

## Cron alignment

Re-import cron jobs after merge so external cron matches weekday ingest schedule:

```bash
CRONJOB_API_KEY=… WORKFLOW_DISPATCH_PAT=… ./scripts/import_cron_jobs.py --job ingest-loop-morning
CRONJOB_API_KEY=… WORKFLOW_DISPATCH_PAT=… ./scripts/import_cron_jobs.py --job ingest-loop-afternoon
```
