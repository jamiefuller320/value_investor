# Data pillar priorities (P1 / P2)

Short ops pointer for spend under the two-pillar plan. Cascade mechanics stay in
[`market-sharded-learning.md`](market-sharded-learning.md); cold-store writers in
[`universe-filing-archive-pack.md`](universe-filing-archive-pack.md).

## P1 — Investment-demanded absolute availability

Close real bind gaps on names Investment uses, in **serve order**:

| Rank | Cohort | Today |
|------|--------|--------|
| 1 | Live holdings | Always in scope |
| 2 | Already-running sealed units | Strand A FTSE buy-tier + N200 `raw_buy_tier` — keep Data SLA |
| 3 | Accepted F3 repair priorities on ranks 1–2 | Negotiation; Data accepts/defers within capacity |
| 4 | **Launch-queue head** | Next newly sealed strategy needing incremental deepen / threshold readiness / distinct shortlist coverage |
| 5 | Other launch-queue waiters | **N201** (`strand-c-short-horizon-value-mom-v0`) waits here after seal — do not parallel-divert P1 |
| Spare | Quiet cold-store | **L499** / **L594** only after ranks 1–4 are green or deferred |

Bind fields (F9 per-name): `key_filing_bodies`, `fcf_basis_bound`, `overlay_bound`,
`memo_recent` (≤21d default). Platform inventory
(`docs/data/decision_input_inventory.json`) holds absolute facts — Investment
reads eligibility and may negotiate; it does not own the join.

### Sealed-strategy launch queue

Each sealed observe/capital strategy is subject to a **launch queue** so new Data
demands do **not starve running units**.

- Sealing enqueues incremental Data work; it does **not** instantly divert P1 from
  holdings or already-running sealed units (e.g. N200 keeps its SLA when N201 seals).
- **N201 sealed 2026-10-12** as observe-only — enqueued as a **waiter** (rank 5
  until it becomes launch-queue head). Do not deepen its shortlist ahead of
  holdings / N200 / accepted F3 repairs.
- Newly sealed strategies wait their turn unless Investment + Data **explicitly**
  re-prioritize the queue head.
- Aligns with: deepen only sealed shortlists, F3 as priority feed, no preemptive
  deepen, clash-aware capacity, no fourth equal sprint.

**When ranks 1–4 are green:** maintain freshness (holdings-first / oldest memo);
do **not** widen rememo caps or invent buy-tier spray. Put quiet spare into
cold-store option value, not a fourth equal sprint.

**F8:** inventory green, repair schedule, or exception alone never applies knobs
or fills.

## P2 — Offline ingest cascade

Unchanged: one fat-slot head to `sprint_ingest_complete`; spare auto-advance;
equal-support after admission; no fourth equal sprint; no shard AI /
`decision-review --apply` without marks.

## Do not deepen preemptively

Add a deepen cohort for a *different* shortlist only when that shortlist is
**sealed** and either is an already-running unit or the **launch-queue head**
(or named tickers are on an accepted F3 repair). N201 is sealed observe-only and
sits in the launch queue as a waiter — do not deepen its universe ahead of
holdings / N200.
