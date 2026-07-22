# Trading 212 coverage overlay

Tradable north star for offline library markets (Invest / Stocks ISA).

## Layout

- `catalogue/` — instruments dump + compact ISIN/shortName index
- `policy.json` — suffix↔exchange hints + venue allowlist fallback
- `exceptions.json` — curated Yahoo-ticker overrides
- `by_market/*` — per-ticker overlay rows
- `summary.json` — rollup stats
- `unavailable_watch.json` — dashboard bypass seed
- `alignment_report.json` — library vs catalogue assessment (`ftse-library t212-align`)

## Commands

```bash
export TRADING212_API_KEY=...
export TRADING212_API_SECRET=...
export TRADING212_ENV=demo   # or live

ftse-library t212-catalogue          # fetch instruments (+ exchanges)
ftse-library t212-overlay            # join library tickers → tradable_on_t212
ftse-library t212-align              # library vs catalogue report
ftse-library ii-overlay              # alias for t212-overlay
```

Catalogue hits are **verified** presence on Trading 212. Allowlist rows are **assumed** when the catalogue is missing or unmatched.

Does not change live FTSE 350 screening. No live order placement (stage 6 / N14).
