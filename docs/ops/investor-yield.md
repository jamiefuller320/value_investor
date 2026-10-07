# Investor net yield (L563)

Gross dividend yield is the cheapness input the models use. For a UK
individual, a foreign dividend is smaller after withholding, and an ISA does
not reclaim that withholding. A taxable account pays the basic-rate dividend
tax, with foreign withholding credited, so the drag is the larger of the two
rates.

`run_library_screen` writes two observe columns on non-UK library screens:

| Column | Meaning |
|--------|---------|
| `investor_net_yield_isa` | Gross × (1 − treaty withholding). UK listings are not given this column. |
| `investor_net_yield_taxable` | Gross × (1 − max(withholding, 8.75%)). Domestic UK would use 8.75% only; those markets are left unchanged. |

8.75% is the ranking assumption for the basic-rate dividend ordinary rate.
Treaty portfolio rates live in `WITHHOLDING_BY_COUNTRY`. A country with no
rate stays blank. This is not a tax computation and it does not change
`assign_signal`, `composite_value`, or the live FTSE screen.

## Automation

- **Trigger:** the library screen, which the ingest cascade already runs.
- **Finding:** `check_investor_yield`. Title **Non-UK library screen has no
  investor net yield** when `latest_signals.csv` exists and lacks the ISA
  column. `auto_fixable` is false. The next screen writes the column.
- **Store:** the column is on `latest_signals.csv` for that market. There is
  no second book.
