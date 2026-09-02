# FCF basis bridges (human review)

When filing-aligned FCF and Yahoo screen TTM diverge by more than **25%**, the screener:

1. Stops using Yahoo TTM as the live FCF input (fail closed).
2. Raises `fcf_basis_overlay`, capping `strong_buy` → `buy` (and `buy` → `hold`).
3. Blocks new deep-research memo spend until a reviewed bridge resolves policy FCF.

## Artifact

Write `docs/data/research/<TICKER>/sources/fcf_bridge.json`:

```json
{
  "ticker": "ITV.L",
  "fiscal_year": "2025",
  "period": "annual",
  "currency": "GBP",
  "resolved": true,
  "policy_basis": "company_adjusted",
  "policy_fcf": 187000000.0,
  "filing_aligned_ocf_minus_capex": 148000000.0,
  "screen_ttm": 211900000.0,
  "company_adjusted": 187000000.0,
  "bridge_steps": [],
  "source_refs": [],
  "reviewed_at": "2026-09-02T11:00:00+00:00",
  "notes": "Policy FCF and why TTM/prior-year figures are diagnostic only."
}
```

`policy_basis` is typically `company_adjusted` or `filing_aligned`. Set `resolved` only after checking the annual filing / RNS against the bridge steps.

## When to review

- Screen / email action notes show **FCF basis mismatch**.
- Dashboard report `fcf.filing_screen_mismatch` is true and `fcf.bridge_resolved` is false.
- Names such as ITV.L / FGP.L / HIK.L after results season when company-defined FCF differs from OCF−CapEx or Yahoo TTM.

## Cadence

Ad hoc when mismatch notes appear on buy-tier names; spot-check Sunday after analysis review if the screen still lists unresolved mismatches.
