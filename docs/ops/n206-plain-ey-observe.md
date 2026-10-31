# N206 plain earnings-yield observe (sealed)

**registration_id:** `strand-d-plain-ey-identity-v0`  
**deferred:** N206  
**Mode:** observe-only — `influences_live` is false. Never writes strand A books, knobs, `max_positions`, `sector_cap`, or `decision-review --apply`  
**Identity:** patient plain EY top-30% local + `financial_health` pass. No momentum filter.  
**Promoted from:** N201 report-only baseline `patient_plain_ey_hold_v0` (new registration; N201 unchanged)

## Learning question

Across live and admitted markets, does a **patient plain earnings-yield top-30%** local book (`financial_health` pass, no momentum filter), sized as a **fixed 100 local-currency stake**, earn a **positive fair-cost episode cohort median**?

Primary = fair-cost episode `%` / `smooth_ret_cohort_median` (not gross; not fund NAV). Cash excess (median minus 0) and stress 3%/side are **report-only**. No market-index series sits on these panels, so that diagnostic is omitted. Alone-first (O3): no pairwise crown versus N200, N201, or N210.

## Seal defaults

| Field | Sealed value |
|---|---|
| Entry | plain EY top-30% local **and** `financial_health` pass; **no** momentum filter |
| Sizing | fixed **100** local-currency units per entry; park cash/fund NAV; score fair-cost episode % |
| DCA | not on v0 (later twin 100/n) |
| Universe | ftse350 + admitted markets; market-native; **no FX** |
| Panels | existing FTSE history + library `signals_*.csv` and `models_*.json.gz` |
| Buy trigger | next eligible weekly refresh after filters clear |
| Exit | 63 trading days **or** identity/quality break, whichever first |
| Costs | fair per-market tables; stress 3%/side report-only |
| Success | fair-cost `smooth_ret_cohort_median` |
| Volume gate | ≥48 completed entries **and** ≥8 calendar weeks |
| Phase floor | ≥8 entries/week (mechanism only) |
| Shrink | new twins / failure-mode ladder — not mid-flight prune |

Amend only via logged change marker or new registration.

## Capacity

Scoring does not add a filing ingest sprint and does not fetch 12–1 price bars. N201 observe was already running when this sealed. Data deepen stays behind holdings and N200. `launch_queue.data_deepen_requested` is false.

## When it runs

| Trigger | Schedule |
|---|---|
| **Daily ops-monitor** | `check_n206_plain_ey_observe` refreshes store |
| **Queue-health refresh** | Projects phase/volume/freshness into `queue_health.n206_pipeline_health` (no re-score) |
| Manual | `ftse-n206-plain-ey --output-dir docs/data` |

## Dashboard

**Analysis → Observe** investment model switcher → **N206 · observe** shows its own lifecycle monitor (phase / volume / path + episodes sample + markers from `n206_plain_ey_observe.json`), pipeline health, companion diagnostics, and the alone path scoreboard. Hash: `#analysis/observe/n206`. Not Strand A’s Lifecycle board; never auto-promote (F8); not an assessment primary.

**Automation → Queue & hunter** shows a compact N206 strip. Observe-only.

## Artifacts

| Path | Role |
|---|---|
| `docs/data/n206_plain_ey_registration.json` | Frozen seal record |
| `docs/data/n206_plain_ey_observe.json` | Episode scoreboard + markers + phase/volume |
| `docs/data/queue_health.json` → `n206_pipeline_health` | Dashboard projection (mechanism only) |
| This doc | Runbook |

Stores commit via ops-monitor `GHA_COMMIT_OPTIONAL`.

## Scoreboards

1. **Path (primary)** — fair-cost `smooth_ret_cohort_median` of fixed-stake episode `%` returns.
2. **Cash excess (report-only)** — that median minus 0.
3. **Stress 3%/side (report-only)** — not promotion truth.
4. **Phase / volume** — mechanism throughput only (F8).

Fixed-stake `%` is **independent of fund NAV**.

## Human volume-gate review

**Sample-thickness** (episodes≥48 and weeks≥8) is a quiet pipeline badge. **Alone-path interestingness** (thickness ∧ fair median > 0) emits **N206 alone-path interesting — promotion design optional (F8)** and may raise Push heat. Open the N206 observe tab / `n206_plain_ey_observe.json`, read the fair-cost path median alone, and stamp disposition **`ack` | `no-design` | `design-open`**. Alone design optional only — **no assessment-primary crown** (O3). **No auto-promote** (F8). Do not promote N200, N201, or N210 from this card.

## Constraints

- Observe-only; `influences_live` false; no live strand A writes; no `--apply`.
- No new screen extras (F4). No momentum price fetch. No filing ingest sprint ahead of holdings or N200.
- F8 fail-closed; F9 binds when present on rows.
- Alone-first (O3). No pairwise compete on v0.
- Does not widen `max_positions` or `sector_cap`.
- No FX conversion on v0. No silent LLM live influence.

## Related

- Fair-cost primacy: [fair-cost-primacy.md](fair-cost-primacy.md) · [market-trading-costs.md](market-trading-costs.md)
- Launch queue: [data-pillar-priorities.md](data-pillar-priorities.md)
- N201 pattern: [n201-value-mom-observe.md](n201-value-mom-observe.md)
