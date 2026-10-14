# Trading 212 coverage overlay

Tradable north star for offline library markets.

- `catalogue/` — instruments dump + compact ISIN/shortName index (`ftse-library t212-catalogue`)
- `policy.json` — suffix↔exchange hints + venue allowlist fallback
- `exceptions.json` — curated ticker overrides
- `by_market/*` — per-ticker overlay (`ftse-library t212-overlay`)
- `summary.json` — rollup stats
- `unavailable_watch.json` — dashboard bypass seed

Does not change live FTSE 350 screening. No live order placement.

**Catalogue env:** `ftse-library t212-catalogue` defaults to `TRADING212_ENV=demo`. Production / Actions-injected keys usually need `TRADING212_ENV=live` (or `--env live`) — see [`catalogue/README.md`](catalogue/README.md).
