# Market-rotating engineering gap burn-down (L448)

Serial **Lane B** escalation for **offline library markets**, aligned with
[`maintenance_slot_cursor.json`](../data/library/maintenance_slot_cursor.json)
(L323 stagger). Keeps admitted / maintenance books from sitting without an eng
task while live FTSE gap-closure pins hold the shared ingest slot.

See also: [`library-ingest-escalation.md`](library-ingest-escalation.md),
[`market-sharded-learning.md`](market-sharded-learning.md),
[`post-run-improvement-clearance.md`](post-run-improvement-clearance.md).

## Problem

- **Lane A** (ingest loop, gap-closure pins) runs per market and scales with
  graduates.
- **Lane B** (`engineering_tasks.json`) is global, deduped, and often filled by
  live FTSE `ingest_gap_closure` tasks.
- Library stall tasks (e.g. DAX) can stay **parked** while only FTSE names
  consume the single open ingest eng slot.

## Policy

| Rule | Detail |
|------|--------|
| **P1 first** | Do not compile library eng work while any **open/pr_open ingest** task is queued (same slot as micro-compile). |
| **Rotation** | Walk maintenance-eligible markets in **`rotate_after(sorted, last_head)`** order — same head as the last maintenance cron slot. |
| **Per market, try in order** | (1) pending gap-closure compile → (2) stall micro-compile → (3) parked-source hunter (prefer this `market_id`). |
| **Not a post-run firehose** | Does not re-open merged post-run titles; use compile-cap drain / Sunday compile for shared scoring gaps. |
| **Pause gates** | Skip when queue-clearing pause or traffic PM pause is active (same as compile-cap drain). |

## When it runs

| Trigger | Command / hook |
|---------|----------------|
| **Ops monitor** (weekday `apply_fixes`) | After idle compile backstop — `try_market_rotating_eng_gap_burndown(apply=True)` |
| **Manual / dry-run** | `ftse-engineering try-market-gap-burndown` (add `--apply` to write tasks) |
| **After library merge** | Existing gap-closure verify rerun hooks unchanged |

## Market universe

Same candidate set as **`list_library_ingest_maintenance_markets`**: admitted
learning markets, ingest parity / exhausted lists, and focus when parity or
exhaustion applies — not “every graduated index at once.”

## Commands

```bash
# Dry-run: show selected market and whether compile would fire
ftse-engineering try-market-gap-burndown --json

# Queue at most one library ingest task when guards pass
ftse-engineering try-market-gap-burndown --apply --json

# Per-market manual (unchanged)
ftse-library gap-closure-engineering-compile --market sp500 --json
ftse-library parked-hunter-compile --market euro_depth --json
```

## Ops interpretation

- **`reason: open ingest engineering task in flight`** — expected while FTSE
  gap-closure (e.g. KGF.L) holds the slot; library rotation resumes when that
  task clears.
- **`reason: no market needs eng escalation`** — gaps closed, stalled task
  already open for that book, or hunter exhausted for rotated markets.
- **`cursor_market_id`** — market at the front of the rotation for this evaluation.

## Human review

- **Parked** library ingest tasks: `ftse-engineering triage-library-stall` (also runs on
  `recover-queue` when tier-1 housekeep is enabled).
- Do not widen to a fourth parallel sprint stream or second concurrent ingest
  eng agent — see [`engineering-sync.md`](engineering-sync.md).
