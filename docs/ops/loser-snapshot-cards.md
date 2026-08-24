# Loser snapshot cards (Tier 1 forensics)

Deterministic **loser-cohort snapshot cards** — human-auditable one-pagers built from
existing screen fields. No agent calls, no full research memos.

## Scope (not the full index)

| Cohort | Included? | Typical count |
|--------|-----------|---------------|
| **avoid** | Yes | ~40–45 names |
| **failed_buy_alumni** | Yes | ~10–15 (memo present, no longer buy-tier) |
| hold (143) | No | — |
| full screened universe (~249) | No | — |

Overlap is allowed (avoid + alumni on the same ticker). Hold-tier names are excluded
unless they have a research memo and left buy-tier (`failed_buy_alumni`).

Optional later cohort: buy-tier hindsight bottom quartile (from exclusion archive) —
not in v1.

## Command

```bash
ftse-loser-snapshot-cards --data-dir docs/data
ftse-loser-snapshot-cards --json
```

## Artifacts

| File | Purpose |
|------|---------|
| `docs/data/loser_snapshot_cards.json` | Structured cards |
| `docs/data/loser_snapshot_cards.md` | Human-readable summary |

Each card includes: screen snapshot, failed families/models, sector peer context,
opinion-flip triggers, and summary lines.

## When to run

Sunday `analysis-review.yml` after `ftse-exclusion-universe-archive` (same data deps:
`latest.json` + research store).

## Relation to loser_pattern_lab

Tier 1 cards feed **analysis-review** (slim `loser_snapshot_cards` → `[scoring]` /
`[offline_sim]` hypotheses) and monthly horizon fragment clustering. Tier 2
(quantitative feature rollups on hindsight bottom quartile) remains planned in
`loser_pattern_lab` vision phase.
