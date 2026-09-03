# FTSE scan-then-target ingest (maintenance)

Live FTSE weekday ingest now **scans buy-tier for new filings**, then deepens a
bounded target list. This replaces blind strong-buy rewalks once hard gaps are
closed, without assuming engineering fetch coverage is ever finished.

Related: [`ingest-backfill-plan.md`](ingest-backfill-plan.md),
[`market-scrutiny.md`](market-scrutiny.md), weekday `ingest-loop.yml`.
Library parity markets use the **same quality bar and deepen volume** via
[`library-ingest-maintenance.yml`](../../.github/workflows/library-ingest-maintenance.yml)
— see [`library-ingest-escalation.md`](library-ingest-escalation.md).

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
| Discovery scan | Buy-tier listing-only. Live FTSE: no throttle today. Library sprint: **time-capped** (≤25% of the slot; critical-path tickers first) so deepen still runs | No |
| Deepen | Top `max_targets` (learning-phase default **62**) | Yes |

### Learning-phase bar (stage 2b)

AI judgment / research overlay needs **filing bodies**, not just index rows.
While compute is unconstrained:

- Weekday cron deepens up to **full buy-tier** (`max_targets=62`, `max_bodies=40`,
  ~60 min runtime).
- After a successful batch, if `indexed_without_body > 0` **and progress was made**,
  the workflow chains another deepen (`drain_generation` 1…`max_drain_generations`,
  default max **12**) until gaps clear or a follow-up stalls with no progress.
- Same-day goal: buy-tier `indexed_without_body` back near **0** after discovery.

Ops monitor (agent / manual catch-up):

```bash
./scripts/monitor_ingest_body_drain.sh --status-only
WORKFLOW_DISPATCH_PAT=… ./scripts/monitor_ingest_body_drain.sh --dispatch-if-idle
```

Re-throttle `max_targets` / daily success cap when GHA minutes bind — do not
weaken discovery or curiosity recording.

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
ftse-ingest-loop run --max-targets 62 --json   # discovery on by default
```

Artifacts are committed by `scripts/push_ingest_loop_artifacts.sh`.

That script restores **only** ingest allowlisted paths from its stash before
commit. It must not check out the whole `docs/data/` tree from the stash WIP
commit — that resurrects stale `ops_status.json` (and similar) when ops-monitor
or other automation lands on `main` mid-run.
