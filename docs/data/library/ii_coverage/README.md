# Interactive Investor coverage overlay (L34 v1)

Exchange-allowlist mapping from II public pages onto offline library tickers, plus optional FIRDS MIC enrichment and an Unavailable bypass watchlist for the dashboard.

- `policy.json` — published venues (Yahoo suffixes + MICs) + next slice candidates
- `exceptions.json` — curated ticker overrides
- `by_market/*.csv` — per-ticker overlay joined by Yahoo ticker
- `summary.json` — rollup stats
- `unavailable_watch.json` — optional server seed/mirror for names bypassed as unactionable on II
- `firds_ii_mics.json` / `.csv` — optional output of `ftse-library firds-filter` (venue admission ≠ II order acceptance)

**Dashboard UX:** Strong buys / Buys cards expose an **Unavailable** button. Bypassed names move to a separate watched list, stay in screening when present in the universe, and are excluded from suggested trades / paper auto-entries until restored. Browser `localStorage` is primary.

**Not** a full broker instrument book. Do not scrape logged-in ii.co.uk.
Does not change live FTSE 350 screening.
