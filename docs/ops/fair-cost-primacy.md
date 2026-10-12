# Fair-cost primacy (standing Investment metric)

**Standing rule:** Cost-aware returns under the project’s **fair** trading-cost
assumptions (T212-shaped / fair cost tables — see
[market-trading-costs.md](market-trading-costs.md)) are the **primary** success
metric for Investment strands, observe instruments, and learning-factory path
scoreboards.

| Layer | Role |
|---|---|
| **Primary** | Absolute smoothed / cohort return **after fair costs** (not gross/pre-cost) |
| **Secondary / report-only** | Market-relative, control excess, stress-cost (e.g. 3% per side) — unless a seal explicitly adds a co-primary |
| **Shape vs measure** | Absolute smoothed return is the usual *shape* of the path primary; fair costs are *how* return is measured |

This does **not** by itself rewrite live Suite A stress books or the assessment
scoreboard product. Existing fair-cost surfaces
([assessment-scoreboard.md](assessment-scoreboard.md), Suite B / fair twins)
already align. Sealed instruments keep their frozen cost stamps until a logged
change marker or new registration.

## Fixed-stake v0 default (new observe / models)

**Standing default** for **new** Investment observe / model instruments (not
N201-only): size as a **fixed-stake mechanical test**, not a fund from day one.

| Layer | v0 default |
|---|---|
| **Stake** | Fixed notional per entry (e.g. **100** units of local / market currency) |
| **Cash / fund NAV** | **Parked** — no cash constraint, no equal-weight book NAV on v0 |
| **Primary scoreboard** | Fair-cost **episode %** (cohort median / sealed metric) — same primacy as above |
| **Later twins** | Portfolio construction, weight caps, cash drag, DCA tranche splits (e.g. **100/n**) — new `registration_id`, not silent v0 defaults |

This does **not** change live strand A capital books or the existing sealed N200
registration. Fair-cost primacy and stress-as-report-only are unchanged. See
also `AGENTS.md` (Dialogue → instrument).

## N200

N200 (`strand-b-plain-value-tech-timing-v0`) scores episode returns with
**fair market-table costs** as the **primary** (`market_trading_costs` /
`ftse350` for the FTSE/LSE archive). Legacy **3% per side** is retained as
**stress / report-only** (`stress_scoreboard_report_only`). Amend logged as
change marker `n200-fair-cost-primary-v1` (same `registration_id`; see
[n200-tech-timing-observe.md](n200-tech-timing-observe.md)).

## Related

- [market-trading-costs.md](market-trading-costs.md) — fair tables vs 3% stress
- [assessment-scoreboard.md](assessment-scoreboard.md) — fair-cost learning table
- [n200-tech-timing-observe.md](n200-tech-timing-observe.md) — sealed observe scoreboard
