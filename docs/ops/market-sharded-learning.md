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
| `observe_sim_markets_mode` | `explicit` | Explicit list starts at `euro_depth`; ingest-profile markets also get the clock |
| `observe_sim_include_ingest_profile` | `true` | Sunday screen-lite + observe sim for focus, sprint streams, ingest-parity, and `ftse_equivalent_markets` |
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
`learning_ready: true` **on raw filing parity**. Leftover unfetchable 8-K / thin
names can be parked (`ingest_exhaustion.json`) so the sprint slot vacates and
learning continues on solid names without waiting for the next periodic report.
Live screen and weekly paper stay on `euro_depth`.

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

**Trading costs:** market shards and observe sims use **fair T212-shaped** per-market assumptions (UK stamp / FX / half-spread), not the live FTSE 3% stress case. See [`market-trading-costs.md`](market-trading-costs.md).

## What “enter learning” means

Shards are **independent stacks** (same processes, separate artifacts, local benchmarks). That is not the same as every shard opening a paper book the day it can print a buy list.

Independence answers *how books are kept apart*. **Gates + capacity** answer *when a book starts*. Do not conflate these four phrases:

| Phrase | What it is | Starts when |
|--------|------------|-------------|
| **Valid buy-tier** | Screen-lite produced `buy` / `strong_buy` names | Metrics floor for screen-lite is met (`effective_min_metrics_for_screen`) |
| **Observe / ingest clock** | Dated archives, observe sim, buy-tier filing deepen | Market is on the ingest profile (focus + sprint + parity + `ftse_equivalent_markets`) |
| **Learning phase** *(P2 / weekly paper)* | Isolated paper book: rules, AI judgment, grace, technical | Phase 1 archive/observe gate **and** a `weekly_paper_shard_markets` slot (depth-first **capacity 1**) |
| **`learning_ready`** | FTSE-equivalent *parity* (canonical filings + 12-week trajectory) | `filing_ready` **and** span ≥12 weeks / 12 unique screen days |

**Start vs promote.** History is **not** required to *open* a frozen buy-tier-level book. It is required to *judge* knobs, claim AI-equivalence, and replay the past. The live FTSE `buy_tier_level` book ([`buy-tier-cohort-labs.md`](buy-tier-cohort-labs.md)) is the intended learning instrument: hold the current raw buy-tier, let full entry/hold/exit lifecycle run, freeze knobs (`is_cohort_lab`). Later filters and “buy now” gates are overlays or counterfactuals on that wide book — not the thing you wait 12 weeks to start.

| Act | Needs | Does not need |
|-----|-------|----------------|
| **Start epoch-zero** | One current screen with a buy-tier, prices, a paper runner | Dated archives, `learning_ready`, leftover-filing perfection |
| **Promote / apply knobs** | Forward marks, N26 floors, cost-aware review | — |
| **Replay below-threshold names** | Layer B snapshots (can start the same week as the book) | A 12-week wait *before* the first fill |

**Cascade intent (serialize, then equalize).** The spare slot is not a permanent second class. One market at a time holds the fat sprint until it reaches the **maintenance ingest threshold**: unmeasured and zero-body are gone, leftover thin/IWB names are parked (`ingest_exhaustion.json` / hunter / next periodic report), and a solid usable set remains. That is `sprint_ingest_complete` — raw `ingest_parity_met` (all four counts zero) or exhaustion. Then:

1. Sprint vacates; the next queue market gets the fat slot.
2. The graduated market joins **steady-state maintenance** at FTSE volume on unparked names (`library-ingest-maintenance.yml`).
3. It is **admitted** to the learning set and should receive **equivalent resource** — same maintenance ingest, screen cadence, paper instrument, and buy-tier rememo as every other admitted market (L321 / L322).

Spare 50%/25% fractions apply only while a market is still *in front* of that threshold, so the head can finish. They are not the long-run treatment.

**What is wired vs not.** Ingest already follows this: exhaustion parks leftovers, vacates the sprint, and puts unparked names on FTSE-volume maintenance (`ingest_exhausted_markets`, today including `sp500`). Learning does **not** flip with it — N94 still keeps weekly paper on `euro_depth`, so a maintenance-threshold market can sit `phase1_ready` with **0** paper batches. That is the busy-but-empty gap: the cascade did its job on filings; equivalent *learning* resource was not switched on.

**Equal treatment after admission.** Compare only admitted markets that have the same package (N103). Do **not** spray leftover plan credit across 21 thin markets (N96). Residual skew you cannot policy away: filing *yield* (ESEF vs EDGAR vs ASX IR), session timezone, and buy-tier width. Spare-slot fractions on a *pre-threshold* market are expected; leaving a *post-threshold* market on observe-sim only is a treatment bug.

**What still waits.** Shard AI-judgment and knob apply wait on the epoch-0 + near-miss watch. Phase 2 weekly AI paper stays on `euro_depth` only. FTSE remains the P1 data lead.

**Admitted start (now).** `sp500` and `asx200` are on `ladder.admitted_learning_markets`. Equivalent resource starts immediately as:

- Frozen weekday/Sunday **epoch-0** `buy_tier_level` book (`ftse-library shard-epoch0`)
- Near-miss watch (`near_miss_watch.json`: buy-not-now, not-buy-tier, hold-near-buy, never-buy-tier)
- Existing maintenance ingest + Layer B screen clock
- **Equal-support package** (`ftse-library equal-support`): market-aware timing stamp, buy-tier rememo eligibility at the same body-lag rule, and per-market exclusion-universe + exit-timing archives under `markets/<id>/screen/`

It does **not** start a shard AI-judgment track or `decision-review --apply`. Watch epoch-0 and the near-miss groups first. FTSE stays the data lead (P1 live ingest / paper-auto). Euro keeps the fat sprint until its own maintenance threshold.

**Equal-support package (market-agnostic).** Once a market is admitted, the same elements apply regardless of exchange suffix:

| Element | Wiring | Not this |
|---------|--------|----------|
| FTSE-volume ingest | Maintenance candidates include admitted ∪ exhausted ∪ parity | Fourth sprint stream |
| Layer B screen clock | `observe_sim_include_admitted` | Focus-only Sunday screens |
| Paper instrument | Frozen `buy_tier_level` | Shard AI / knob apply |
| Buy-tier rememo | Same `rememo_body_lag_threshold` on that market's buy-tier | `research_all_graduated` / 21-market spray (N96) |
| Buy-not-now | `timing_signal=wait` on buy-tier (Yahoo via market mapper, PIT on dated archives) | LSE `.L` rewrite |
| Not-buy-tier | Current below-buy-tier + `never_buy_tier` from dated archives; exit-timing archive on `screen/history/` | FTSE-only `docs/data/history` |

```bash
ftse-library equal-support
ftse-library equal-support --markets sp500,asx200
```

**Knob apply is the AI-track gate.** `decision-review --apply` retunes picking knobs (`skip_timing_wait`, `min_conviction`, `sector_cap`). Frozen `buy_tier_level` is `is_cohort_lab=true` and cannot apply. Do not apply knobs on a shard until AI is a track, and do not make AI a track until the watch period has marks on epoch-0 **and** the near-miss groups. They are one decision, not two.

**Runner wall-clock.** Work around it by **staggering** and by **parallel maintenance**, not by a fourth equal sprint.

| Approach | Use when | Do not use when |
|----------|----------|-----------------|
| **Stagger** | One market still holds the fat sprint. Existing +30/+60 min stream offsets, maintenance at `:30`, spare wait-on-head, and session timezones (AU / EU / US weekday paper) | As a substitute for admitting a post-threshold market |
| **Parallel pipelines** | Graduated markets on **maintenance** (FTSE-volume, unparked names) plus one fat **sprint** head | A fourth equal sprint stream while a head is unfinished |
| **One maintenance job, many markets** | Two markets, short deepen | Several admitted books at `max_targets=62` / 3600s — the job is sequential and `timeout-minutes: 120` will clip the tail (L323) |

Hosted Actions minutes are not the bind (N66). What still collides if you naive-parallel: per-job timeouts, `push_library_ingest_artifacts` checkout races, and **source** rate limits (ESEF / EDGAR / IR / Yahoo) — staggering helps those more than a fourth workflow does.

**Below-tier protection against tight knobs** is a second instrument, not a reason to delay the wide book. A buy-tier-only book never sees names that never hit buy-tier. “Buy-tier but not buy now” is already the first cut on FTSE (`buy_tier_level` uses `skip_timing_wait=true`, so `timing_signal=wait` stays out). Full-screened exclusion-universe and exit-timing near-miss labs cover the rest **on FTSE** once ≥2 weekly snapshots exist. Shards get that clock by taking Layer B screens from week 0 (L320) — they do not need those archives *before* the first fill.

### Practical limits (why not every shard yesterday)

Book isolation is already true: shards do **not** write FTSE `docs/data/latest.json` or FTSE `paper_automation/` configs, and shard `decision-review` runs with `apply=False` until Phase 3 + N26. Live-book contamination is not the binding constraint.

What *is* binding if “apply FTSE machinery to all shards as soon as possible” means the full weekday stack (ingest volume, rememo, paper tracks, review, human spot-check):

| Constraint | Why it does not parallelize cleanly |
|------------|-------------------------------------|
| **Shared producers** | Ingest runners, Sunday ladder, `weekly_ops`, engineering queue, and human review are one pool. The ingest cascade already makes spare streams wait on `euro_depth` so they cannot starve the head. Full FTSE ingest volume (62 targets, ≤4×/day) on every shard would invert that. |
| **Calendar span** | Phase 1 / `learning_ready` need dated Sunday archives. Extra jobs do not create 12 unique weeks. |
| **Filing yield** | Same `ingest-loop` ≠ same bodies. ESEF / EDGAR / ASX IR / leftover 8-Ks differ. AI tracks without bodies are observe noise. |
| **Unequal treatment** | Pre-threshold spare fractions are expected. Post-threshold observe-sim-only (N94) confounds market vs support. |
| **`weekly_ops` spray** | One envelope funds focus-market buy-tier research + Sunday email. N96: leftover plan credit is not 21-market memo density. Equal *admitted-set* rememo is different (L321). |
| **Weekly paper slot** | Capacity 1 is a treatment choice, not a CPU wall. A `phase1_ready` market still sits in Phase 1 with blocker `{id} not in weekly_paper_shard_markets`. |
| **Weekday replica** | Overlay refresh, rememo, 62-target ingest, session/timezone cron, human spot-check. Phase 3 stays **one** non-FTSE weekday pilot at a time. |
| **Phase 4** | Live-screen inclusion is a **project** gate (FTSE 2b persistent excess **and** one shard through Phase 3), not per-shard independence. |

**Independent promotion when robust is the intended Phase 1–3 end-state** — once the market is admitted **and** given the same support package. Do not read observe-sim on a spare slot as a comparable result. Ingest runner wall-clock is still shared; Cursor plan credit is not the reason support is unequal.

Ticker-level research is also not a perfect air gap: observe-sim / shard paper read focus research ∪ every other `markets/*/screen/research` so sibling-home memos work for dual-listed names. That is not book-P&L contamination.

Admission at `sprint_ingest_complete` (exhaustion or raw parity) is L322. The equal-support package after that is L321. Weekday epoch-zero without a 12-week wait is L319. Do not treat spare ingest job count as learning progress (N102) and do not compare pre-threshold leftovers to an admitted book (N103).

## Phases and timescale

Use **Sunday ladder cycles** and **archive counts**, not calendar deadlines. The Sunday quiet bundle is the natural heartbeat (~1 screen-lite pass per market per week when that market is in the maintenance/screen set).

### Phase 1 — Observe sim shards

**What runs:** After screen-lite in `ftse-library ladder`, `run_observe_sims_for_screened_markets` refreshes frozen-signal sims (screen rules / research overlay / AI judgment) vs local benchmark. Writes `screen/sim/observe_summary.json`.

**Policy:** `ladder.observe_sim_after_screen`, `ladder.observe_sim_markets_mode`, optional `ladder.observe_sim_markets` / `observe_sim_markets_extra`, plus `ladder.observe_sim_include_ingest_profile` (default **on**).

**Markets mode (depth-first):** `explicit` with `observe_sim_markets: ["euro_depth"]` for the weekly-paper pilot. The observe **clock** is a standard ingest-profile step: focus + `ingest_parallel_sprint` / `_2` + `ingest_parity_markets` + `ftse_equivalent_markets` + weekly-paper shards (currently `euro_depth`, `sp500`, `asx200`). Layer A grow-only markets stay off the clock. Legacy `graduated_benchmark` mode remains available for breadth experiments.

**Screen cadence:** Ladder backfills memo-free screen-lite for observe-sim markets that the research / focus pass did not already screen (`observe_sim_screen_missing_markets`, default on). This runs on a normal Sunday as well as when research is skipped, so sprint/parity markets keep dated archives instead of stalling to focus-only cadence.

**Exit gate (per market):** ≥ **12** dated `signals_YYYYMMDD_HHMMSS.csv` files under `markets/<id>/screen/` (same bar as backtest history and L127 revisit). When `phase1_require_ai_beat_rules` is true (code default), AI must also beat rules on observe sim; depth-first policy sets this **false** until filing parity.

| Market (benchmark wired) | Benchmark | Phase 1 notes |
|--------------------------|-----------|---------------|
| `euro_depth` | ^STOXX50E | Depth-first pilot — sole **weekly paper** slot; also on the ingest-profile observe clock |
| `sp500` | ^GSPC | Sprint / `ftse_equivalent_markets` **measurement** clock; not in weekly shard list under depth-first |
| `asx200` | ^AXJO | Parallel sprint stream 2 — same ingest-profile observe clock as S&P |
| `euro_stoxx50` | ^STOXX50E | Component of `euro_depth`; demoted from weekly slot |

**Timescale:** New depth book needs ~**11 Sunday ladder cycles** (~3 months at weekly cadence) before Phase 2 evidence is meaningful.

### Phase 2 — Weekly paper shard *(wired Aug 2026)*

**What runs:** Full track set (rules, AI judgment, grace, technical), exit-shadow and exit-timing cohorts, churn health — **Sunday batch only** after ladder, using library screen → reports adapter. No weekday settle stepping yet; no `--apply` on knobs.

**Policy:** `ladder.weekly_paper_shard_after_screen`, `ladder.weekly_paper_shard_markets`, `ladder.weekly_paper_shard_capacity` (depth-first: capacity **1**, markets `["euro_depth"]`). Ingest effort follows the same cascade (P2 in [`AGENTS.md`](../AGENTS.md)): fat slot on the current learning-phase candidate, spare on the next queue markets, no fourth equal sprint stream.

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

**Concurrency:** **One** non-FTSE weekday pilot at a time (ops/review load, not book isolation).

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
# S&P 500 FTSE-equivalent depth (canonical filings + trajectory).
# Sunday observe-sim also persists learning_depth.json; CLI is a manual refresh.
ftse-library learning-depth --market sp500 --json
ftse-library learning-depth --market sp500 --write --write-trajectory

# Manual observe sim refresh (Phase 1)
ftse-library sim --markets euro_depth

# Phase gates and advancement triggers
ftse-library shard-status
ftse-library shard-status --markets euro_depth --json

# Admitted epoch-0 (buy-tier-level + near-miss; no AI)
ftse-library shard-epoch0
ftse-library shard-epoch0 --markets sp500,asx200

# Equal-support package (timing, near-miss groups, counterfactual archives)
ftse-library equal-support
ftse-library equal-support --markets sp500,asx200

# Manual Phase 2 weekly paper batch
ftse-library shard-paper --markets euro_depth

# Policy
ftse-library policy   # observe_sim_markets_mode, weekly_paper_shard_capacity

# Sunday ladder (automatic observe sim + weekly paper shard when eligible)
ftse-library ladder
```

## Capacity tiers (summary)

```text
Tier 1 — Phase 1 observe sim     ingest profile (focus + sprint + parity + equivalent)
Tier 2 — Phase 2 weekly paper  weekly_paper_shard_markets[:capacity]  (depth-first cap 1)
Tier 3 — Phase 3 weekday shard   one manual pilot at a time
```

## Research overlay and rememo (all in-scope markets)

One resolver (`research/market_store.py`) maps memos for **whatever market is in
scope** — FTSE live (`docs/data/research/`) or any library shard
(`markets/<id>/screen/research/`), plus sibling-home memos when a name was first
written under another index slice.

| Surface | What it reads |
|---------|----------------|
| Sunday publish / weekday rememo | This-run `output/research` ∪ committed store ∪ `research[]` |
| Weekday paper-auto overlay | Same union (committed inferred as `latest.json` sibling `research/`) |
| Observe sim / shard paper | Focus research dir ∪ every other `markets/*/screen/research` |

Ladder selective research (`rememo_existing`, default on) still skips **fresh**
memos, but rememos buy-tier names when ingest has added enough filing bodies
(same lag rule as FTSE weekday rememo). Before a rememo, focus-market
canonical filings are copied into the existing memo home so Sunday eligibility
clears after the rewrite. A new focus / sprint / parity market inherits this
without a per-market hook.

## Guardrails

- Shards do **not** write FTSE `docs/data/latest.json` or FTSE `paper_automation/` configs.
- Knob apply on shards stays off until Phase 3 and N26 history floors per track.
- `weekly_ops` funds **euro_depth** selective research — not round-robin across 21 thin markets.
- FTSE stage 2b primary track remains the capital-attention loop until it beats ^FTSE.
