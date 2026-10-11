# Data pillar priorities (P1 / P2)

Short ops pointer for spend under the two-pillar plan. Cascade mechanics stay in
[`market-sharded-learning.md`](market-sharded-learning.md); cold-store writers in
[`universe-filing-archive-pack.md`](universe-filing-archive-pack.md).

## P1 — Investment-demanded absolute availability

Close real bind gaps on names Investment uses:

| Cohort | Today |
|--------|--------|
| Live holdings | Always in scope |
| Active sealed shortlists | FTSE buy-tier (strand A + N200 `raw_buy_tier`) |
| Accepted F3 repair priorities | When Investment negotiates a repair; Data accepts/defers within cascade capacity |

Bind fields (F9 per-name): `key_filing_bodies`, `fcf_basis_bound`, `overlay_bound`,
`memo_recent` (≤21d default). Platform inventory
(`docs/data/decision_input_inventory.json`) holds absolute facts — Investment
reads eligibility and may negotiate; it does not own the join.

**When the active set is green:** maintain freshness (holdings-first / oldest
memo); do **not** widen rememo caps or invent buy-tier spray. Put quiet spare
into cold-store option value (**L499** writers / deferred **L594**), not a
fourth equal sprint.

**F8:** inventory green, repair schedule, or exception alone never applies knobs
or fills.

## P2 — Offline ingest cascade

Unchanged: one fat-slot head to `sprint_ingest_complete`; spare auto-advance;
equal-support after admission; no fourth equal sprint; no shard AI /
`decision-review --apply` without marks.

## Do not deepen preemptively

Add a deepen cohort for a *different* shortlist only when that shortlist is
**sealed** (or named tickers are on an accepted F3 repair). N201 stays
define-only until a separate seal — do not pre-deepen its draft universe.
