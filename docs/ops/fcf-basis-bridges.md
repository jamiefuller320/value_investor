# FCF basis bridges (auto policy + residual override)

When filing-aligned FCF and Yahoo screen TTM diverge by more than **25%**, the screener:

1. Stops using Yahoo TTM as the live FCF input (fail closed).
2. Raises `fcf_basis_overlay`, capping `strong_buy` → `buy` (and `buy` → `hold`).
3. Locks **policy FCF automatically** via majority / filing fallback (see below).
4. Optional: a reviewed `fcf_bridge.json` can override the auto pick.

## Automatic policy (default — no human required)

Three bases are compared:

| Basis | Source |
|-------|--------|
| `screen_ttm` | Yahoo trailing free cash flow |
| `filing_aligned` | Annual OCF − CapEx from cached financials |
| `company_adjusted` | Company/IR prose figure when extractable |

Rules (`reconcile_fcf` → `pick_fcf_majority_policy`):

1. If a pairwise majority agrees within **25%**, use that pair and **discard the outlier**. Preference inside the pair: company-adjusted → filing-aligned → screen TTM. Pair order: company+filing, then company+screen, then filing+screen (Yahoo never wins alone).
2. If pairs disagree or the third source is missing, **fall back to official filing-aligned** OCF−CapEx.
3. Company-adjusted alone only if filing is missing; screen TTM alone only if both filing and company-adjusted are missing.

`fcf.bridge_resolved` / `fcf.auto_policy_resolved` / `fcf.auto_policy_*` surface the outcome on reports. Deep-research memo gating treats auto-resolved policy the same as a human bridge.

## Optional human override artifact

Write `docs/data/research/<TICKER>/sources/fcf_bridge.json` only when the auto pick is wrong (definition fights: leases, M&A, one-offs the majority mishandles):

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
  "notes": "Override auto policy when majority/filing fallback is wrong."
}
```

`policy_basis` is typically `company_adjusted` or `filing_aligned`. A resolved bridge always wins over auto majority.

## When to review (residual)

- Auto policy chose a figure you disagree with after reading the annual / RNS.
- So-what `human_gate` for `fcf_bridge_needed` (rare): buy-tier mismatch note with **no** filing-aligned or company-adjusted figure available.
- Spot-check Sunday if action notes still look wrong after auto resolution.

## Cadence

No standing human gate for ordinary mismatches. Residual overrides are ad hoc.

## Automation vs human

- **Auto:** majority discard-outlier + filing fallback; fail-closed overlay; so-what enforcement queue when overlay missing.
- **Human (residual):** optional `fcf_bridge.json` override when auto policy is wrong, or when no filing/company figure exists.
- Runbook: [so-what-gap-closure.md](so-what-gap-closure.md)
