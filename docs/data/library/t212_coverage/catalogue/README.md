# Trading 212 catalogue

Fetch with:

```bash
export TRADING212_API_KEY=...
export TRADING212_API_SECRET=...
export TRADING212_ENV=demo   # or live
ftse-library t212-catalogue
```

Writes `instruments.json` (gitignored), `index.json`, `fetched_at.json`, and optionally `exchanges.json`.
