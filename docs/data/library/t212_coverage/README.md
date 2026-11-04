# Trading 212 coverage overlay

Tradable north star for offline library markets.

- `catalogue/` — instruments dump + compact ISIN/shortName index (`ftse-library t212-catalogue`)
- `policy.json` — suffix↔exchange hints + venue allowlist fallback
- `exceptions.json` — curated ticker overrides
- `by_market/*` — per-ticker overlay (`ftse-library t212-overlay`)
- `summary.json` — rollup stats
- `unavailable_watch.json` — dashboard bypass seed

Does not change live FTSE 350 screening. No live order placement.
