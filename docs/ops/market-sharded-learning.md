# Market-sharded learning stacks

Independent per-market replicas of the FTSE learning pipeline — same *processes*, separate *shards* (universe, benchmark, configs, artifacts). No combined mega-book.

Live FTSE 350 screen and weekday primary learning track stay unchanged (stage 2b). Breadth grows as **offline / parallel paper shards** until promotion gates clear.

See also: [`PROJECT_OBJECTIVE.md`](../PROJECT_OBJECTIVE.md), [`primary-learning-track.md`](primary-learning-track.md), [`market-scrutiny.md`](market-scrutiny.md).

## Depth-first EU pilot *(Aug 2026)*

Policy focus is **`euro_depth`**: EURO STOXX 50 ∪ low-overlap periphery
(`aex`, `bel20`, `smi`, `omxs30`, `atx`, `psi20`, `iseq20`) ≈ **150–250** unique
names (currently ~194). One book, benchmark `^STOXX50E`.

| Knob | Depth-first value | Effect |
|------|-------------------|--------|
| `focus_market` | `euro_depth` | Ladder grow/screen/research target |
| `research_all_graduated` | `false` | Selective research only on focus (stops 21-market memo spray) |
| `observe_sim_markets_mode` | `explicit` | Observe sim only `euro_depth` |
| `weekly_paper_shard_markets` | `["euro_depth"]` | Capacity 1 isolated learning book |
| `phase1_require_ai_beat_rules` | `false` | Phase 1→2 on archives until filing parity (L166) |
| `focus_graduation.auto_advance` | `false` | Do not advance focus away from the pilot |

Other graduated markets stay **Layer A maintenance only**. FTSE live learning is unchanged.
Do **not** expand with DAX/CAC/MIB until this pilot has euro_filings depth comparable
to FTSE buy-tier.

**S&P 500 FTSE-equivalent depth** is a **parallel ingest + measurement** track, not a
live-screen / weekly-paper expansion. Policy `ftse_equivalent_markets: ["sp500"]`
forces **canonical-only** filing coverage under
`docs/data/library/markets/sp500/screen/research/{TICKER}/`. nasdaq100 (or any other
shard) indexes must not be counted as S&P parity. Do **not** append `sp500` to
`ingest_parity_markets` until `ftse-library learning-depth --market sp500` reports
`learning_ready: true`. Live screen and weekly paper stay on `euro_depth`.

**30-day sprint:** compressed phase gates + weekday ingest/shard automation — see
[`euro-depth-sprint.md`](euro-depth-sprint.md).

```bash
ftse-library grow --market euro_depth
ftse-library ladder                 # research + observe + weekly shard for euro_depth
ftse-library shard-status --markets euro_depth
```

## Architecture

| Shard root | Role |
|------------|------|
| `docs/data/paper_automation/` | FTSE 350 live learning (4 strategy tracks) |
| `docs/data/library/markets/<id>/screen/sim/` | Phase 1 observe sim (frozen screen history) |
| `docs/data/paper_automation/markets/<id>/` | Phase 2+ full paper stack |
| `docs/data/library/shard_phases.json` | Committed phase rollup (advancement triggers) |
| `docs/data/paper_automation/markets/<id>/shard_phase.json` | Per-market phase status + blockers |
| `docs/data/paper_automation/markets/<id>/weekly_batch_log.json` | Phase 2 weekly batch marks |

Each non-FTSE shard compares excess vs a **local benchmark** (`^GSPC`, `^STOXX50E`, `^IETP`, …).

## Phases and timescale

Use **Sunday ladder cycles** and **archive counts**, not calendar deadlines. The Sunday quiet bundle is the natural heartbeat (~1 screen-lite pass per market per week when that market is in the maintenance/screen set).

### Phase 1 — Observe sim shards

**What runs:** After screen-lite in `ftse-library ladder`, `run_observe_sims_for_screened_markets` refreshes frozen-signal sims (screen rules / research overlay / AI judgment) vs local benchmark. Writes `screen/sim/observe_summary.json`.

**Policy:** `ladder.observe_sim_after_screen`, `ladder.observe_sim_markets_mode`, optional `ladder.observe_sim_markets` / `observe_sim_markets_extra`.

**Markets mode (depth-first):** `explicit` with `observe_sim_markets: ["euro_depth"]`. Legacy `graduated_benchmark` mode remains available for breadth experiments.

**Screen cadence:** When selective research is skipped (`weekly_ops` exhausted, checkpoint, or `--skip-research`), ladder runs a memo-free screen-lite pass for observe-sim markets (`observe_sim_screen_when_research_skipped`, default on) so Phase 1 archives do not stall to focus-only cadence.

**Exit gate (per market):** ≥ **12** dated `signals_YYYYMMDD_HHMMSS.csv` files under `markets/<id>/screen/` (same bar as backtest history and L127 revisit). When `phase1_require_ai_beat_rules` is true (code default), AI must also beat rules on observe sim; depth-first policy sets this **false** until filing parity.

| Market (benchmark wired) | Benchmark | Phase 1 notes |
|--------------------------|-----------|---------------|
| `euro_depth` | ^STOXX50E | Depth-first pilot — sole observe/weekly slot |
| `sp500` | ^GSPC | FTSE-equivalent **measurement** track (`ftse_equivalent_markets`); not in weekly shard list under depth-first |
| `euro_stoxx50` | ^STOXX50E | Component of `euro_depth`; demoted from weekly slot |

**Timescale:** New depth book needs ~**11 Sunday ladder cycles** (~3 months at weekly cadence) before Phase 2 evidence is meaningful.

### Phase 2 — Weekly paper shard *(wired Aug 2026)*

**What runs:** Full track set (rules, AI judgment, grace, technical), exit-shadow and exit-timing cohorts, churn health — **Sunday batch only** after ladder, using library screen → reports adapter. No weekday settle stepping yet; no `--apply` on knobs.

**Policy:** `ladder.weekly_paper_shard_after_screen`, `ladder.weekly_paper_shard_markets`, `ladder.weekly_paper_shard_capacity` (depth-first: capacity **1**, markets `["euro_depth"]`).

**Orchestration:** After observe sim in `ftse-library ladder`, `run_weekly_paper_shards_for_screened_markets` runs for markets that passed Phase 1 and were screened this run. Phase rollup refreshes to `docs/data/library/shard_phases.json`.

**Strong-buy metrics probe (L153):** After maintenance, when the engineering queue is idle, the ladder re-fetches metrics for offline screen `strong_buy`/`buy` names on Phase 2 then observe-sim markets (`strong_buy_metrics_probe_*` policy knobs). Surfaces provider failures early and can draft a coverage task; does **not** run FTSE-style filing ingest on non-UK names — deepen via `euro_filings` for the pilot instead.

**Enter when:** Phase 1 gate met for that market **and** market is in `weekly_paper_shard_markets`.

**Exit gate:** ≥ **8** weekly batch marks in `weekly_batch_log.json`; `learning_tracks_review.json` shows `beat_control=true` on latest review.

**Advancement triggers (automatic):**

| Trigger | Source | Effect |
|---------|--------|--------|
| Phase 1 → 2 | `phase1_gate_met()` — ≥12 archives, ≥12 observe snapshots; AI-beat-rules only if `phase1_require_ai_beat_rules` | Eligible for weekly paper shard when in policy |
| Phase 2 → 3 | `phase2_gate_met()` — ≥8 weekly batches + beat_control | `shard_phase.json` reports `next_phase=3`; weekday shard still manual |
| Rollup refresh | Every ladder pass + `ftse-library shard-status` | Updates `shard_phases.json` and per-shard `shard_phase.json` with blockers |

**Timescale:** **8 Sunday cycles** hands-off after the first weekly batch deploy (~2 months).

**Pilot order:** `euro_depth` first (depth-first). Revisit `sp500` weekly paper only after
`learning-depth` is green (canonical filing + 12-week trajectory). Do not ingest all 503
constituents — buy-tier depth only.

### Phase 3 — Weekday paper shard *(one market at a time, 8–12 weeks)*

**What runs:** Weekday `paper-auto`-equivalent for the shard (local session/settle), `decision-review --apply` scoped to shard configs only.

**Enter when:** Phase 2 exit met **and** [promotion criteria](#promotion-criteria-l127) satisfied for that market.

**Concurrency:** **One** non-FTSE weekday pilot at a time until L107 dashboard panel ships.

**Exit gate:** ≥ **8** weekly marks on weekday cadence; ≥ **15** closed exit-shadow episodes per primary track (N25/N26 floors); local-benchmark excess stable over rolling window.

**Timescale:** **8–12 weeks** hands-off per pilot after launch (≈2–3 months calendar at 5-day cadence).

### Phase 4 — Live screen inclusion *(stage 4 project gate)*

**What runs:** Non-UK names eligible on dashboard live screen / publish path (still not a combined book).

**Enter when:** FTSE primary AI-judgment shows **persistent** excess vs ^FTSE; **one** shard cleared Phase 3; data-quality and liquidity floors documented.

**Timescale:** Project stage gate — not calendar-driven. Revisit N17 / L26 when Phase 3 pilot completes.

### Phase 5 — Cross-shard winner selection *(stage 6 precursor, not built)*

**What runs:** Observe-only ranking of survivors across **≥2** Phase-3 shards into a deployable book (benchmark-relative excess, conviction, T212 tradability). Shards remain independent learning stacks; this layer does **not** merge books prematurely.

**Enter when:** Vision phase `cross_shard_winner_selection` triggers — see [`learning-director-vision.md`](learning-director-vision.md) and `docs/data/learning_director_vision.json`.

**Prerequisite:** FTSE `filtered_cohort_track` active with ≥8 epoch marks (within-shard convergence first).

## End-to-end timeline (realistic)

```text
Now          Focus euro_depth; seed constituents (~194); grow metrics + screen archives
~0–3 mo      euro_depth reaches 12 screen archives / observe snapshots (AI gate off)
~2–4 mo      euro_depth Phase 2 weekly shard (8 Sundays) while deepening euro_filings
~4–7 mo      Phase 3 weekday pilot only after filing/memo parity looks FTSE-like
Stage 4      Live screen expansion — after FTSE 2b + shard Phase 3 evidence
```

Calendar ranges assume regular Sunday ladders and no long CI/library outages. **Slip the calendar if gates fail** — do not promote on thin history.

## Promotion criteria (L127)

A market may graduate from **Phase 1 observe sim** to **Phase 2 weekly paper shard** when:

1. ≥ 12 dated screen-lite CSV archives.
2. Observe sim `snapshot_count` ≥ 12 in latest `observe_summary.json`.
3. AI-judgment track **beat rules control** on local benchmark over the last 8 snapshots — **required only when** `ladder.phase1_require_ai_beat_rules` is true (depth-first `euro_depth` keeps this false until filing parity).

A market may graduate from **Phase 2** to **Phase 3 weekday shard** when:

1. Phase 2 weekly marks ≥ 8.
2. AI-judgment **beat rules** on shard churn-health window.
3. No open engineering task blocking metrics/screen for that market.
4. Human ack in ops review (monthly horizon scan or manual).

## Commands

```bash
# S&P 500 FTSE-equivalent depth (canonical filings + trajectory)
ftse-library learning-depth --market sp500 --json
ftse-library learning-depth --market sp500 --write --write-trajectory

# Manual observe sim refresh (Phase 1)
ftse-library sim --markets euro_depth

# Phase gates and advancement triggers
ftse-library shard-status
ftse-library shard-status --markets euro_depth --json

# Manual Phase 2 weekly paper batch
ftse-library shard-paper --markets euro_depth

# Policy
ftse-library policy   # observe_sim_markets_mode, weekly_paper_shard_capacity

# Sunday ladder (automatic observe sim + weekly paper shard when eligible)
ftse-library ladder
```

## Capacity tiers (summary)

```text
Tier 1 — Phase 1 observe sim     explicit [euro_depth] under depth-first policy
Tier 2 — Phase 2 weekly paper  weekly_paper_shard_markets[:capacity]  (depth-first cap 1)
Tier 3 — Phase 3 weekday shard   one manual pilot at a time
```

## Guardrails

- Shards do **not** write FTSE `docs/data/latest.json` or FTSE `paper_automation/` configs.
- Knob apply on shards stays off until Phase 3 and N26 history floors per track.
- `weekly_ops` funds **euro_depth** selective research — not round-robin across 21 thin markets.
- FTSE stage 2b primary track remains the capital-attention loop until it beats ^FTSE.
