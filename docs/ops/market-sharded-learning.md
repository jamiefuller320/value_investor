# Market-sharded learning stacks

Independent per-market replicas of the FTSE learning pipeline — same *processes*, separate *shards* (universe, benchmark, configs, artifacts). No combined mega-book.

Live FTSE 350 screen and weekday primary learning track stay unchanged (stage 2b). Breadth grows as **offline / parallel paper shards** until promotion gates clear.

See also: [`PROJECT_OBJECTIVE.md`](../PROJECT_OBJECTIVE.md), [`primary-learning-track.md`](primary-learning-track.md), [`market-scrutiny.md`](market-scrutiny.md).

## Architecture

| Shard root | Role |
|------------|------|
| `docs/data/paper_automation/` | FTSE 350 live learning (4 strategy tracks) |
| `docs/data/library/markets/<id>/screen/sim/` | Phase 1 observe sim (frozen screen history) |
| `docs/data/paper_automation/markets/<id>/` | Phase 2+ full paper stack *(not wired yet)* |

Each non-FTSE shard compares excess vs a **local benchmark** (`^GSPC`, `^STOXX50E`, `^IETP`, …).

## Phases and timescale

Use **Sunday ladder cycles** and **archive counts**, not calendar deadlines. The Sunday quiet bundle is the natural heartbeat (~1 screen-lite pass per market per week when that market is in the maintenance/screen set).

### Phase 1 — Observe sim shards *(start now)*

**What runs:** After screen-lite in `ftse-library ladder`, `run_observe_sims_for_screened_markets` refreshes frozen-signal sims (screen rules / research overlay / AI judgment) vs local benchmark. Writes `screen/sim/observe_summary.json`.

**Policy:** `ladder.observe_sim_after_screen`, `ladder.observe_sim_markets`.

**Exit gate (per market):** ≥ **12** dated `signals_YYYYMMDD_HHMMSS.csv` files under `markets/<id>/screen/` (same bar as backtest history and L127 revisit).

| Market | Screen archives (Aug 2026) | Phase 1 status |
|--------|----------------------------|----------------|
| `sp500` | 12 | **Ready** — gate met |
| `euro_stoxx50` | 13 | **Ready** — gate met |
| `iseq20` | 1 | **Accumulating** — ~11 more Sunday passes |

**Timescale:** Markets already at 12 archives are done with Phase 1 *accumulation* today. New graduates need ~**11 Sunday ladder cycles** (~3 months at weekly cadence) before Phase 2 evidence is meaningful.

**Parallelism:** Add markets to `observe_sim_markets` as soon as benchmark is wired; sim runs even with thin history (caveat in summary JSON) but **do not promote** on &lt;12 archives.

### Phase 2 — Weekly paper shard *(engineering + 8 Sundays)*

**What runs:** Full track set (rules, AI judgment, grace, technical), exit-shadow and exit-timing cohorts, churn health — **Sunday batch only** after ladder, using library screen → reports adapter. No weekday settle stepping yet.

**Enter when:** Phase 1 gate met for that market **and** engineering delivers shard adapter + orchestrator hook.

**Exit gate:** ≥ **8** weekly batch marks per shard; churn health populated; AI vs rules separation visible in shard rollup (same spirit as `learning_tracks_churn_health`).

**Timescale:** **8 Sunday cycles** hands-off after the first weekly batch deploy (~2 months). Build work for the first pilot (`sp500`) can start in parallel with `iseq20` Phase 1 accumulation.

**Pilot order:** `sp500` → `euro_stoxx50` → `iseq20` (largest history first).

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

## End-to-end timeline (realistic)

```text
Now          Phase 1 observe sim for sp500 + euro_stoxx50 + iseq20 (policy)
~0–3 mo      iseq20 reaches 12 screen archives; sp500/euro already there
~1–2 mo      Phase 2 engineering for sp500 weekly shard (parallel with above)
~2–4 mo      sp500 Phase 2 hands-off (8 Sundays)
~4–7 mo      sp500 Phase 3 weekday pilot if promotion bar met
~7+ mo       Second shard (euro_stoxx50) only after first pilot stable
Stage 4      Live screen expansion — after FTSE 2b + shard Phase 3 evidence
```

Calendar ranges assume regular Sunday ladders and no long CI/library outages. **Slip the calendar if gates fail** — do not promote on thin history.

## Promotion criteria (L127)

A market may graduate from **Phase 1 observe sim** to **Phase 2 weekly paper shard** when:

1. ≥ 12 dated screen-lite CSV archives.
2. Observe sim `snapshot_count` ≥ 12 in latest `observe_summary.json`.
3. AI-judgment track **beat rules control** on local benchmark over the last 8 snapshots (same-window comparison in observe summary).

A market may graduate from **Phase 2** to **Phase 3 weekday shard** when:

1. Phase 2 weekly marks ≥ 8.
2. AI-judgment **beat rules** on shard churn-health window.
3. No open engineering task blocking metrics/screen for that market.
4. Human ack in ops review (monthly horizon scan or manual).

## Commands

```bash
# Manual observe sim refresh (Phase 1)
ftse-library sim --markets sp500,euro_stoxx50,iseq20

# Policy
ftse-library policy   # ladder.observe_sim_markets

# Sunday ladder (automatic observe sim when market screened)
ftse-library ladder
```

## Guardrails

- Shards do **not** write FTSE `docs/data/latest.json` or FTSE `paper_automation/` configs.
- Knob apply on shards stays off until Phase 3 and N26 history floors per track.
- `weekly_ops` caps selective research — full stacks for 21 markets at FTSE depth is out of scope; round-robin research continues.
- FTSE stage 2b primary track remains the capital-attention loop until it beats ^FTSE.
