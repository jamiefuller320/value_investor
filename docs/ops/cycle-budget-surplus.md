# Cycle-end budget surplus

At the end of a Cursor billing cycle, leftover **plan credit** can fund a
**provisional** raise of the weekly orchestrator envelope (`weekly_ops_cap_usd`).
The bump is reviewed at the **next** cycle end and kept or reverted.

This is **not** a rememo-cap raise. Weekday rememo stays at 3 names/day (N77).

Cursor does not expose remaining credits to `CURSOR_API_KEY`. Unused fraction
comes from the usage page (declared).

## What transfers

| Input | Default | Role |
|-------|---------|------|
| `--unused-fraction` | required | Unused Ultra (or other plan) share, e.g. `0.40` |
| `--plan-monthly-usd` | `200` (Ultra) | Included pool for the math |
| `--transfer-fraction` | `0.25` | Share of leftover that becomes steady-state |
| `--max-weekly-bump-usd` | `20` | Hard cap on the weekly raise (also ≤ 50% of current cap) |

Example: 40% unused of a $200 Ultra cycle → $80 leftover → 25% = $20 → **$5/week**
→ `weekly_ops_cap` $80 → $85. Review on the next refresh-day cycle (`2026-10-d8`
when current is `2026-09-d8`).

## Commands

```bash
# After a rememo / director–worker burst, or on surplus day
ftse-library cycle-surplus assess --unused-fraction 0.40 --plan-monthly-usd 200

# Apply the proposed bump (writes policy + docs/data/cycle_budget_surplus.json)
ftse-library cycle-surplus apply --update-plan-metadata --plan-name "Cursor Ultra"

# Next cycle end — recommendation only, then decide
ftse-library cycle-surplus review
ftse-library cycle-surplus review --keep
ftse-library cycle-surplus review --revert
```

`--keep` / `--revert` are refused until `cycle_id` reaches `review_cycle_id`.

Keep when weekly_ops regularly used the extra room (spent > 80% of the *old*
cap). Revert when leftover stayed high.

## Artifacts

| File | Role |
|------|------|
| `docs/data/cycle_budget_surplus.json` | Last assess / apply / review snapshot |
| `docs/data/library/policy.json` → `budget.cycle_surplus_provisional` | Provisional cap + review gate |
| `docs/data/library/policy.json` → `budget.weekly_ops_cap_usd` | Live envelope |

## Human gate

Monthly, around the plan refresh day (default the 8th): read the surplus
artifact, run `review`, and keep or revert. Do not raise rememo daily caps from
the same leftover.

Checklist: [human-tasks-checklist.md](human-tasks-checklist.md) · cadence:
[ops-review-cadence.md](ops-review-cadence.md).
