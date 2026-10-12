# N201 value-mom observe (sealed)

**registration_id:** `strand-c-short-horizon-value-mom-v0`  
**deferred:** N201  
**Mode:** observe-only — never writes strand A books, knobs, or `decision-review --apply`  
**Independent of:** sealed N200 (`strand-b-plain-value-tech-timing-v0`)

## Learning question

Across live ∪ admitted markets, do observe-only **selective** ~3m **plain-EY + momentum** entries (market-native, no FX), sized as a **fixed-stake mechanical test**, beat a **patient plain-value hold** on the same eligible set after **fair local costs**?

Primary = fair-cost episode `%` / `smooth_ret_cohort_median` (not gross; not fund NAV). Patient-hold excess + stress 3%/side = **report-only**.

## Seal defaults

| Field | Sealed value |
|---|---|
| Entry | plain EY top-30% local **and** 12–1 momentum > 0 **and** `financial_health` pass |
| Sizing | fixed **100** local-currency units per entry; park cash/fund NAV; score fair-cost episode % |
| DCA | not on v0 (later twin 100/n) |
| Universe | ftse350 + admitted markets; market-native; **no FX** |
| Buy trigger | next eligible weekly refresh after filters clear |
| Exit | 63 trading days **or** identity/quality break, whichever first |
| Costs | fair per-market tables; stress 3%/side report-only |
| Success | fair-cost `smooth_ret_cohort_median`; patient-hold excess report-only |
| Volume gate | ≥48 completed entries **and** ≥8 calendar weeks |
| Phase floor | ≥8 entries/week (mechanism only) |
| Shrink | new twins / failure-mode ladder — not mid-flight prune |

Amend only via logged change marker or new registration.

### Patient-hold baseline (pinned)

| Field | Value |
|---|---|
| **id** | `patient_plain_ey_hold_v0` |
| **Definition** | Same universe; plain EY top-30% local; **no** momentum filter; same `financial_health` pass; same 63 trading-day or identity/quality-break exit; same fixed 100 local stake; fair per-market costs |
| **Role** | Report-only excess vs strategy (not co-primary) |

### Eligibility / soft gaps (MVP)

| Item | Note |
|---|---|
| **eligibility_mode** | `entry_fields_required_f9_or_pass` |
| **Entry fields** | Rows need `earnings_yield` (+ local top-30%), `momentum_12_1` (or weekly price proxy), and `financial_health_pass` / model pass |
| **Soft gap** | Live FTSE history often lacks those fields → zero episodes until enrichment; fail-closed for capital (F8) |
| **Hold proxy** | 63 trading days ≈ weekday count on weekly archive (no holiday calendar) |
| **Admitted markets** | Walker primarily consumes ftse350 history plus any enriched `market_id` rows |

Same spirit as N200’s archive MVP `row_fields_or_pass` — soft gaps documented, capital still fail-closed.

## Launch queue

Sealing **enqueues** N201 Data demand (deepen / shortlist / threshold readiness). It does **not** steal P1 from live holdings or already-running sealed units (N200). N201 waits as a launch-queue waiter unless Investment + Data explicitly re-prioritize. See [data-pillar-priorities.md](data-pillar-priorities.md).

## When it runs

| Trigger | Schedule |
|---|---|
| **Daily ops-monitor** | `check_n201_value_mom_observe` refreshes store |
| **Queue-health refresh** | Projects phase/volume/freshness into `queue_health.n201_pipeline_health` (no re-score) |
| Manual | `ftse-n201-value-mom --output-dir docs/data` |

## Artifacts

| Path | Role |
|---|---|
| `docs/data/n201_value_mom_registration.json` | Frozen seal record |
| `docs/data/n201_value_mom_observe.json` | Episode scoreboard + markers + phase/volume |
| `docs/data/queue_health.json` → `n201_pipeline_health` | Dashboard projection (mechanism only) |
| This doc | Runbook |

Stores commit via ops-monitor `GHA_COMMIT_OPTIONAL`.

## Scoreboards

1. **Path (primary)** — fair-cost `smooth_ret_cohort_median` of fixed-stake episode `%` returns.
2. **Patient-hold excess (report-only)** — strategy median minus patient baseline median.
3. **Stress 3%/side (report-only)** — not promotion truth.
4. **Phase / volume** — mechanism throughput only (F8).

Fixed-stake `%` is **independent of fund NAV** — cash drag / equal-weight book construction parked on v0.

## Constraints

- Observe-only; no live strand A writes; no `--apply`.
- No new screen extras (F4).
- F8 fail-closed; F9 binds when present on rows.
- Independent of N200 (dual observe OK; ≤1 live promotion path).
- No FX conversion on v0.

## Related

- Fair-cost primacy: [fair-cost-primacy.md](fair-cost-primacy.md) · [market-trading-costs.md](market-trading-costs.md)
- Launch queue: [data-pillar-priorities.md](data-pillar-priorities.md)
- N200 pattern: [n200-tech-timing-observe.md](n200-tech-timing-observe.md)
- Project store: `alternate-strand-learning-questions.md`, `lifecycle-learning-flow.md`
