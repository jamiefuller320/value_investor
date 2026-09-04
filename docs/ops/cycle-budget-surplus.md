# Cycle-end budget surplus

At the end of a Cursor billing cycle, leftover **plan credit** can fund a
**provisional** raise of the weekly orchestrator envelope (`weekly_ops_cap_usd`).
The bump is reviewed at the **next** cycle end and kept or reverted.

This is **not** a rememo-cap raise. Weekday rememo stays at 3 names/day (N77).

Cursor does not expose remaining credits to `CURSOR_API_KEY`. Unused fraction
comes from the usage page (declared).

## Two spend meters (do not mix)

Cursor bills (or depletes) two different things. This repo only ledgers one.

| Meter | Where you see it | What it measures | Used for |
|-------|------------------|------------------|----------|
| **Included plan credit** | Usage page % used / leftover | Pro-rata draw on the Ultra (or Pro) included pool | Surplus assess `--unused-fraction` |
| **Estimated on-demand USD** | `policy.budget.estimated_spend_*` | API list-price proxy (`MODEL_API_RATES`, ~$0.40/memo, ~$3.66/director–worker) | `weekly_ops_cap_usd` envelope |

A rememo burst can move the usage-page leftover by ~1% while the policy ledger only adds a few dollars. That is expected: included-credit units are not API list-price dollars. **Do not** infer leftover USD from `estimated_spend / usage-page %`.

`--unused-usd` is only for an operator-declared leftover in dollars. Prefer `--unused-fraction` from the usage page. `plan_monthly_usd` stays metadata (listed plan price) and must not be invented to force the two meters to match.

`weekly_ops_cap_usd` is denominated in the **estimated-USD** ledger. Transferring a share of leftover *plan %* into that cap is a policy heuristic, not a unit conversion. Review keep/revert on the usage-page leftover, not on whether estimated token $ “used up” the surplus.

## Weekly ops plan-credit ceiling (15%)

Overall weekly ops is capped at **15% of listed plan credit per week**
(`budget.weekly_ops_plan_credit_share_cap`, default `0.15`). On a $200 Ultra
listing that is **$30/week**. The other ~85% of included credit stays available
for development work and other projects.

This is generous on a single-market FTSE live path. It becomes the binding
constraint once the researched universe is large enough that Sunday + weekday
ops would otherwise consume more than 15% of the included pool.

Surplus assess / apply **cannot raise** `weekly_ops_cap_usd` past this ceiling.
If the live cap is already above it, assess action is `clamp_to_ceiling` and
apply lowers the envelope. Review `--revert` also respects the ceiling (it will
not restore $80 or $120 once the 15% rule is in force).

Do not raise the 15% share to spend leftover Ultra. Rememo daily caps stay at 3.

## What transfers

| Input | Default | Role |
|-------|---------|------|
| `--unused-fraction` | optional | Unused Ultra (or other plan) share, e.g. `0.40` |
| `--unused-usd` | optional | Declared leftover USD (preferred when leftover exceeds listed plan price) |
| `--plan-monthly-usd` | `200` (Ultra) | Included pool for fraction math only — do not invent a new Ultra price |
| `--transfer-fraction` | `0.25` | Share of leftover that becomes steady-state |
| `--max-weekly-bump-usd` | `20` | Hard cap on the weekly raise (also ≤ 50% of the *rebase* cap) |
| `--plan-credit-share-cap` | `0.15` | Max weekly_ops as a share of `plan_monthly_usd` |
| `--replace-provisional` | off | Rebase on the original weekly_ops cap instead of stacking |

Example (transfer math only, before the 15% ceiling): 40% unused of a $200 Ultra
cycle → $80 leftover → 25% = $20 → **$5/week**. Under the standing 15% rule the
proposed cap is `min($80+$5, $30) = $30`. A live cap of $80 or $120 is clamped
down, not raised.

If the usage-page unused fraction changes, re-assess with `--unused-fraction` and
`--replace-provisional`. Do not raise `--max-weekly-bump-usd` or
`--plan-credit-share-cap` to chase leftover *plan %*.

## Commands

```bash
# After a rememo / director–worker burst, or on surplus day
ftse-library cycle-surplus assess --unused-fraction 0.40 --plan-monthly-usd 200

# Recalibrate from the usage-page fraction (do not infer leftover USD from burst token $)
ftse-library cycle-surplus assess --unused-fraction 0.36 --replace-provisional

# Apply the proposed bump (writes policy + docs/data/cycle_budget_surplus.json)
ftse-library cycle-surplus apply --replace-provisional --update-plan-metadata --plan-name "Cursor Ultra"

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
the same leftover. Do not lift the 15% weekly-ops plan-credit ceiling to absorb
leftover included credit.

Checklist: [human-tasks-checklist.md](human-tasks-checklist.md) · cadence:
[ops-review-cadence.md](ops-review-cadence.md).
