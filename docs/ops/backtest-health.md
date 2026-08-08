# Backtest history health

Automated monitoring, safe repair, and readiness reporting for archived weekly
run snapshots (`docs/data/history/run_*.json.gz`).

## Goals

- **Monitor** snapshot integrity (schema, benchmark, price coverage, duplicates)
- **Repair** only by quarantining corrupt, duplicate, or orphan (unpaired) files — never rewrite payloads
- **Enhance** readiness metrics (`backtest_ready`, horizon count) in `backtest_health.json`
- **Protect** publish path from invalid new snapshots polluting git-tracked history

## Pollution guards

| Rule | Rationale |
|------|-----------|
| No Yahoo backfill into old snapshots | Would fake point-in-time prices |
| No in-place JSON edits | Quarantine + human review instead |
| Publish skips invalid **new** run files | `publish_committed_run_history` validation gate |
| Existing committed files never overwritten by repair | Repair only moves bad files to `quarantine/` |

## CLI

```bash
# Audit committed history
ftse-backtest-health --audit-only

# Audit + write docs/data/backtest_health.json
ftse-backtest-health

# Quarantine corrupt/duplicate files, then refresh status
ftse-backtest-health --apply
```

## Ops monitor integration

Daily `ftse-ops-monitor` now:

1. Runs `check_backtest_history()` on `docs/data/history/`
2. Auto-quarantines fixable issues (corrupt JSON, duplicate plain+gzip twins, run snapshots without a `models_` pair)
3. Writes `docs/data/backtest_health.json` with readiness + recomputed backtest summary

Warn-only when `valid_runs < 2` (history still seeding).

## Artifacts

| File | Purpose |
|------|---------|
| `docs/data/backtest_health.json` | Latest audit, issues, readiness |
| `docs/data/history/quarantine/` | Quarantined corrupt/duplicate snapshots |

## Related

- [`architecture.md`](../architecture.md) — run snapshot schema
- [`ops-monitor.md`](ops-monitor.md) — daily ops checks
- [`data-backup.md`](data-backup.md) — tier-1 backup includes `docs/data/history/`
