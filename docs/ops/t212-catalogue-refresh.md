# Trading 212 catalogue refresh (L665)

The offline library uses a committed snapshot of which instruments Trading 212
lists as tradable. That snapshot powers `t212_coverage` overlays (ISIN / shortName
joins with venue allowlist fallback). It must stay fresh enough that overlay hits
remain trustworthy.

## Schedule

| Trigger | When |
|---------|------|
| GitHub schedule | Monday **05:00 UTC** (`.github/workflows/t212-catalogue-refresh.yml`) |
| Manual | `workflow_dispatch` on the same workflow |

## Secrets and environment

| Secret / env | Purpose |
|--------------|---------|
| `TRADING212_API_KEY` | API key (repo secret) |
| `TRADING212_API_SECRET` | API secret (repo secret) |
| `TRADING212_ENV=live` | Set in the workflow job; catalogue scope needs **live** |

If either API secret is missing, the workflow **soft-skips** with a clear log line
and exits **0** (no failure email). Ops-monitor still warns via
`check_t212_catalogue_freshness` until a successful refresh lands in git.

## What the workflow runs

Uses existing CLI — no duplicated fetch logic:

1. `ftse-library t212-catalogue --env live --root docs/data/library` — read-only
   `GET /api/v0/equity/metadata/instruments` (+ exchanges when available).
2. `ftse-library t212-overlay --root docs/data/library` — rebuild per-market overlays.

Never calls order or account-trading endpoints.

Committed paths (only when changed):

- `docs/data/library/t212_coverage/catalogue/**`
- `docs/data/library/t212_coverage/by_market/**`
- `docs/data/library/t212_coverage/summary.json`

## Local drill-down

```bash
export TRADING212_API_KEY=… TRADING212_API_SECRET=… TRADING212_ENV=live
ftse-library t212-catalogue --env live
ftse-library t212-overlay
```

## Ops-monitor staleness

Daily `collect_ops_findings` calls `check_t212_catalogue_freshness`:

| Condition | Severity | Title |
|-----------|----------|-------|
| `fetched_at.json` age ≤ **14 days** | `info` | Trading 212 catalogue fresh |
| Missing / unreadable meta or age **> 14 days** | `warn` | Trading 212 catalogue stale |

`auto_fixable=False` — human adds secrets or dispatches the workflow; no ingest/rememo
spray from the finding alone. Listed in [ops-monitor.md](ops-monitor.md).

Human step when refresh never ran: add **`TRADING212_API_KEY`** and
**`TRADING212_API_SECRET`** to repo secrets, then dispatch the workflow or wait for
the Monday slot.
