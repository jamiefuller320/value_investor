# Buy-tier chart outcome review (observe-only)

Deterministic rollup of **dashboard price-chart JSON** after a recommendation is
on the book. Scores each buy-tier name against **frozen initial levels** (the
first week of the current signal), not the latest refreshed trade plan.

Does **not** apply decision-review knobs, change paper books, or open
engineering tasks.

## Why

Chart popups now show:

- a vertical **signal since** marker
- **initial recommendation** levels (core / tactical / stop / target / SMAs)
- **first crossings** of those frozen levels

A human can see that the story is often mixed, that stops are rarely hit, and
that some entries were well timed. This module makes that read checkable and
repeatable. How tactical buy vs target spread is floored (cost + reward:risk) is
documented in [trade-plan-target-spread.md](trade-plan-target-spread.md).

## How to read a mixed pass

Short-term underwater names are **not** chart failures if the investment
hypothesis still stands. That is the same stance as
[hypothesis-integrity.md](hypothesis-integrity.md) (`hold_tolerate` for intact
theses). The test of these picks is the **longer path** — paper excess after
costs and later Sunday refreshes — not the first month of open returns.

Do **not** retune entry timing from a mixed_no_terrible pass. A later timing
overlay might cut some mis-timed buys, but it has to be scored against the
cost of missing names that eventually work. A chart-side **drop-to-recovery**
label (max drop after the frozen entry, then days/return back through that
entry) is parked until several Sunday refreshes exist. Paper already collects
hold-recovery / breakeven on stressed *positions*
([exit-timing-cohorts.md](exit-timing-cohorts.md)); the chart metric would
cover the whole buy-tier path, not only paper sleeves.

## Command

```bash
ftse-chart-outcomes --data-dir docs/data
ftse-chart-outcomes --json
```

## Artifacts

| File | Purpose |
|------|---------|
| `docs/data/chart_outcome_review.json` | Structured verdict, counts, per-name rows |
| `docs/data/chart_outcome_review.md` | Human-readable summary |

`ftse-publish` also embeds a slim `chart_outcome_review` object in
`docs/data/latest.json` for the dashboard.

## Outcome labels

Entry price is `initial_levels.last` (recommendation-week close). Gap opens after
`signal_since` do not rewrite the entry.

| Label | Meaning |
|-------|---------|
| `well_timed` | Target hit and still non-negative with a shallow drawdown, or ≥5% with shallow drawdown |
| `giveback` | Target hit, then faded below the entry |
| `underwater` | Negative open return, no target hit, not terrible |
| `intact_positive` | Modest gain, no well-timed trigger |
| `flat` | Unchanged since entry |
| `terrible` | Open return ≤ −15%, drawdown ≤ −25%, or stop hit with return ≤ −10% |
| `insufficient_data` | No usable entry / series |

**Verdict** `mixed_no_terrible` means well-timed names and faded/underwater names
both exist, and `terrible` is zero.

## When it runs

| Trigger | Schedule |
|---------|----------|
| `ftse-publish` | After buy-tier charts are copied to the dashboard |
| Sunday `analysis-review.yml` | After trajectory evidence (soft-fail) |
| Manual | `ftse-chart-outcomes` |

## Yahoo GBp↔GBP unit flips (L482)

Yahoo LSE history sometimes mixes **pence (GBp)** and **pounds (GBP)** in one
close series. A single ~100× session jump then scores as a −99% “terrible”
path (seen on BCG.L / HEAD.L; historically MEGP.L / ROSE.L).

**Mitigation (shared helper `yahoo_price_units`):**

1. `fetch_price_history` / chart build — normalize OHLC/close series when
   consecutive prints sit in the ~100× band (factor 100, ratio band 80–125).
2. `score_chart_payload` — defensive re-normalize of committed chart JSON and
   align frozen `initial_levels.last` to the series unit before returns.
3. Affected rows carry `price_unit_normalization`; rollups expose
   `price_unit_flips`.

Real multi-month distress without a ~100× discontinuity is left unchanged.

### Refresh so the dashboard shows fixed numbers

After this code lands (or after charts are rebuilt):

```bash
# Re-score committed chart JSON (no Yahoo re-fetch) → updates
# docs/data/chart_outcome_review.json|.md used by the Analysis panel.
ftse-chart-outcomes --data-dir docs/data

# Full rebuild of chart payloads + slim embed in latest.json:
# runs inside ftse-publish / Sunday analysis-review after charts copy.
ftse-publish
```

The dashboard loads `data/chart_outcome_review.json` directly (see `docs/app.js`),
so a `ftse-chart-outcomes` commit is enough for the panel; `latest.json` picks
up the slim copy on the next publish.

## Guardrails

- Observe-only — **not** a paper/learning outcome label yet
- Do not feed first-cross dates into `ftse-decision-review` from this file
- Do not retune entry timing from a mixed_no_terrible pass
- Frozen `assign_signal()` thresholds stay off-limits (N3)

See [analysis-review.md](analysis-review.md#chart-outcomes-observe-only).
