# FTSE scan-then-target ingest (maintenance)

Live FTSE weekday ingest now **scans buy-tier for new filings**, then deepens a
bounded target list. This replaces blind strong-buy rewalks once hard gaps are
closed, without assuming engineering fetch coverage is ever finished.

Related: [`ingest-backfill-plan.md`](ingest-backfill-plan.md),
[`market-scrutiny.md`](market-scrutiny.md), weekday `ingest-loop.yml`.

## Flow

```text
bootstrap (seed missing indexes)
    → listing-only discovery across buy-tier (RNS / Investegate / CH / IR)
    → diff vs filings_index; merge new rows (no body download)
    → record curiosity (unknown sources / hosts)
    → rank targets (gap scores + discovery bonus)
    → deepen top max_targets (existing ingest-improvement pass)
```

| Phase | What | Bodies? |
|-------|------|---------|
| Discovery scan | All buy-tier (`scan_cap=None`, no throttle today) | No |
| Deepen | Top `max_targets` (default 12) | Yes |

Pinned gap-closure / verification reruns skip the full scan (single-ticker cost).

## Curiosity

Novel filing `source` labels and unfamiliar URL hosts are written to:

- `docs/data/ingest_discovery_curiosity.json`
- `docs/data/ingest_discovery_scan_summary.json`

`engineering_never_complete: true` is intentional — each market’s fetch surface
keeps evolving; curiosity feeds future eng work rather than declaring idle.

## Prioritisation (later throttle hooks)

Weights live in `DEFAULT_PRIORITIZATION_WEIGHTS` (`ingest_discovery_scan.py`):

| Weight | Default | Role |
|--------|---------|------|
| `new_index_rows` | 8 | Base bonus when any new listing rows appear |
| `new_index_row_cap` | 10 | Cap on per-row add-on |
| `unknown_source` | 4 | Curiosity: unknown filing source |
| `unknown_host` | 2 | Curiosity: unfamiliar URL host |

No compute throttle today. When GHA minutes become scarce, set
`discovery_scan_cap` and/or reweight — do not remove curiosity recording.

## Commands

```bash
ftse-ingest-loop status --json
ftse-ingest-loop run --max-targets 12 --json   # discovery on by default
```

Artifacts are committed by `scripts/push_ingest_loop_artifacts.sh`.
