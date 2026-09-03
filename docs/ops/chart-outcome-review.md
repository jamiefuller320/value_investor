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
repeatable.

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

## Guardrails

- Observe-only — **not** a paper/learning outcome label yet
- Do not feed first-cross dates into `ftse-decision-review` from this file
- Frozen `assign_signal()` thresholds stay off-limits (N3)

See [analysis-review.md](analysis-review.md#chart-outcomes-observe-only).
