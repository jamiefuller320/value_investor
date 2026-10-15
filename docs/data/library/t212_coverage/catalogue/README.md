# Trading 212 catalogue

Fetch with:

```bash
export TRADING212_API_KEY=...
export TRADING212_API_SECRET=...
# CLI/client default is demo. Production / Actions-injected keys usually need live
# (demo.trading212.com returns 401 for keys issued against the live API).
export TRADING212_ENV=live
# or: ftse-library t212-catalogue --env live
ftse-library t212-catalogue
```

Use `TRADING212_ENV=demo` only with a demo-issued key. Pair each key with the env it was created for; do not assume the default demo host.

Writes `instruments.json` (gitignored), `index.json`, `fetched_at.json`, and optionally `exchanges.json`.
