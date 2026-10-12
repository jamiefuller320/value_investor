# N200 tech-timing observe (sealed)

**registration_id:** `strand-b-plain-value-tech-timing-v0`  
**deferred:** N200  
**Mode:** observe-only — never writes strand A books, knobs, or `decision-review --apply`

## Learning question

On threshold-eligible names, does **raw buy-tier** identity with calendar **±14d** entry/exit timing brackets beat default timing (offset 0) on cost-aware **`smooth_ret_cohort_median`** measured at **fair market-table costs**?

Episode returns deduct fair T212-shaped friction from `market_trading_costs` (FTSE/LSE archive → `ftse350`: stamp + half-spread). Project-wide standing rule: [fair-cost-primacy.md](fair-cost-primacy.md). Legacy **3% per side** is kept as **stress / report-only** (control median + episode diagnostic), not promotion truth.

## Seal defaults (O2–O6)

| ID | Choice |
|---|---|
| O2 identity | `raw_buy_tier` |
| O3 volume gate | ≥24 completed entry episodes **and** ≥8 calendar weeks |
| O4 smoother | `smooth_ret_cohort_median` (fair-cost episode returns) |
| O5 primacy | Absolute smoothed return **primary** at fair costs; control excess + stress 3% **report-only** |
| O6 phase floor | 5 entries/week (illustrative) |

Amend only via logged change marker or new registration.

### Cost stamp (amended in place)

| Field | Value |
|---|---|
| **Primary** | Fair market table (`market_trading_costs` / `ftse350`) — buy + sell sides |
| **Stress / report-only** | `stress_trade_cost_pct = 0.03` per side |
| **registration_id** | Unchanged (`strand-b-plain-value-tech-timing-v0`) |
| **Change marker** | `n200-fair-cost-primary-v1` |

Kept the same `registration_id` because this is an exploratory cost-stamp correction on a still-open observe unit, not a new learning question or identity. History is not silently rewritten: the observe store appends the marker and registration records `cost_amendment`.

## When it runs

| Trigger | Schedule |
|---|---|
| **Daily ops-monitor** | `check_n200_tech_timing_observe` refreshes store |
| **Queue-health refresh** | Projects phase/volume/freshness into `queue_health.n200_pipeline_health` (no re-score) |
| Manual | `ftse-n200-tech-timing --output-dir docs/data` |

## Dashboard

**Automation → Queue & hunter** shows **N200 / learning-factory pipeline** (phase floor, volume gate, **per-lever entry/exit verdicts**, store freshness, ops-check). Compact strip also on **Analysis → observe**.

Phase green = **mechanism throughput** only. Lever win/lose = **best-feasible under ±14d brackets at fair costs**, independent of path P&L. Neither is alpha or capital readiness (F8). Projection helper: `build_n200_pipeline_health_projection` → `queue_health.n200_pipeline_health.per_lever`.

## Artifacts

| Path | Role |
|---|---|
| `docs/data/n200_tech_timing_registration.json` | Frozen seal record (+ cost_basis / stress fields) |
| `docs/data/n200_tech_timing_observe.json` | Bracket + **per-lever** scoreboards + markers + phase/volume + stress diagnostic (Pages sidecar) |
| `docs/data/queue_health.json` → `n200_pipeline_health` | Dashboard projection (phase / volume / **per_lever** / freshness) |
| This doc | Runbook |

Stores commit via ops-monitor `GHA_COMMIT_OPTIONAL`.

## Scoreboards

1. **Path** — control cell `entry_+0__exit_+0` absolute median of **fair-cost** episode returns (primary — [fair-cost-primacy.md](fair-cost-primacy.md)).
2. **Per-lever** — `entry_lever_scoreboard` / `exit_lever_scoreboard` + rollup `per_lever_scoreboards`: control offset `0` vs ±14d alternatives at **fair costs**, other timing lever held at control. Verdict `win` / `tie` / `lose` / `insufficient` is **independent of path P&L** (lever can win on a losing book). Marker `n200-per-lever-scoreboard-v1`.
3. **Phase** — entries/week vs sealed floor.
4. **Diagnostics** — full cell matrix + best-cell; **stress 3%** control median (`stress_scoreboard_report_only`) — not a promote signal (F8).

## Constraints

- No live strand A writes; no `--apply`.
- No new screen extras (F4).
- F9 binds when present on archive rows; else `row_fields_or_pass` for MVP archive (still fail-closed for capital).
- N201 sealed independently (`strand-c-short-horizon-value-mom-v0`); dual observe OK; ≤1 live promotion path.

## Related

- Fair-cost primacy: [fair-cost-primacy.md](fair-cost-primacy.md) · [market-trading-costs.md](market-trading-costs.md)
- Project store: `alternate-strand-learning-questions.md`, `lifecycle-learning-flow.md`
- Post-hsr policy: `docs/ops/post-hsr-freeze-extras.md`
