# Interactive Investor coverage overlay (L34 v1)

Exchange-allowlist mapping from II public pages onto offline library tickers.

- `policy.json` — published venues + next slice candidates
- `exceptions.json` — curated ticker overrides
- `by_market/*.csv` — per-ticker overlay joined by Yahoo ticker
- `summary.json` — rollup stats

**Not** a full broker instrument book. Do not scrape logged-in ii.co.uk.
Does not change live FTSE 350 screening.
