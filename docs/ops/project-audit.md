# Project audit (logic, data spec, deferred)

Dated integrity pass against the stage-2b learning contract: weekday paper-auto /
AI-judgment should see filings, FCF basis, overlay bind, and memo recency on
FTSE holdings and buy-tier. Offline library stays cascaded (P2). This page is a
snapshot plus the commands to re-run the same checks — not a new human cadence.

**As of:** 2026-09-07 · agent run `bc-58e13586-9496-4300-8dcc-0be00303f9e3`

## Re-run

```bash
ftse-ingest-audit --no-write
ftse-analysis-review system-gaps
ftse-progress-report build
ftse-defer list
ftse-defer list --fragments
```

North star: [`PROJECT_OBJECTIVE.md`](../PROJECT_OBJECTIVE.md). Data model:
[`architecture.md`](../architecture.md). Spend order: [`AGENTS.md`](../../AGENTS.md).

## What is in place and working

| Piece | Intended job | Status |
|-------|----------------|--------|
| FTSE 350 screen + Sunday publish | Stage 0 core | Working. Universe stays FTSE 350. |
| Weekday paper-auto + overlay refresh | Bind latest memos before trades | Working. 2026-09-07 run succeeded at 08:26 UTC. Ops-monitor “overdue” at 07:46 UTC was pre-settle, not a missed weekday. |
| AI-judgment vs rules vs ^FTSE | Stage 2b primary track | Wired correctly (`adjusted_signal` + `research_verdict=accumulate`). Still underperforms ^FTSE after **stress** costs; beats the rules control. Do not add tracks to “fix” excess (N49). |
| FCF basis overlay | Cap `adjusted_signal` when Yahoo TTM ≠ filing FCF | Wired into the signal paper-auto reads. |
| Scan-then-target ingest | Discover new filings, deepen buy-tier | Implemented (weekday `max_targets=62` + drain). |
| Admitted shards `sp500`, `asx200` | Epoch-0 buy-tier-level + equal-support; no shard AI yet | Policy matches doctrine. Do not fork AI / `--apply`. |
| Observe-sim | Frozen screen history vs local benchmark | Running; not promotion evidence. |

## Data specification vs the learning task

Stage 2b consumes a **thin, correct** slice of captured data. Memo prose,
`risk_tags`, `question_outcomes`, and `memo_quality` are for humans, rememo, and
observability — not paper eligibility (N27). That split is intentional.

| Captured field | Specified for paper-auto? | Finding |
|----------------|---------------------------|---------|
| `research_verdict` / `adjusted_signal` | Yes — the gate | Correct and bound on weekday refresh. |
| `fcf_basis_overlay` | Yes | Correct; now also persisted on history snapshots. |
| Filing bodies | Indirectly (memo + FCF + EPS overlays) | Bodies exist on live buy-tier. Screen EPS-from-body overlays were computed but **dropped** from published reports; reports now export `interim_eps_decline_pct` / `adjusted_eps_growth_pct`. |
| Memo recency / `memo_quality` | No (rememo only) | Correct as non-gate. Stale memos can still drive accumulate. |
| History `run_*.json.gz` overlay columns | Needed for replay | Snapshot writer now keeps overlay/EPS columns when present. Historical analysis also uses PIT memos (`get_research_as_of`). |
| Euro_depth library memos | Observe-sim AI uses `accumulate` | **17/18 sampled memos had 0 filing bodies** with accumulate verdicts. That is observe noise (`market-sharded-learning.md`). System-gaps now flags thin library memos even when the ladder executed ≥1 name this pass. |

Live ingest audit (2026-09-07, after body-path fix): 61 buy-tier names, 61 memos,
0 zero-body tickers, 6 indexed-without-body (`SHEL.L`, `FGP.L`, `IMB.L`, `ITV.L`,
`SBRY.L`, `SRP.L`), 40 AI-eligible accumulate names. Body parsers that resolve
on disk: **7** (was 0 when the audit joined `body_path` incorrectly). Published
`reports[]` still show 0 EPS percents until the next Sunday screen rebuilds
`CompanyReport` with the new fields. Residual index gaps are weekday-drain /
unfetchable leftovers, not a missing Sunday screen.

## Deferred ideas incorporated or closed

**Already shipped — marked `done`:** L194, L195, L196 (scan-then-target + ingest
lifecycle), L188 (Sunday review tables), L141 (horizon memo-schema question),
L211 (IR metrics in gap-fill pack), L198 (Sunday SP500 screen-lite clock),
L106 / L122 (browser sandbox labelled vs server tracks), L278 (no fourth equal
sprint), fragment `frag-20260811-04` (autofix PR comment).

**Incorporated now (P1):** **L123** — Sunday `--ingest-improvement-cap` raised
from 20 to **62** (same constant as weekday learning-phase deepen) so post-screen
memos see bodies.

**Still parked (revisit unmet or not P1/P2):** L111, L121, L33, L125, L147,
L202, L208, N27 (do not gate AI on memo_quality yet), N48/N49, shard AI on
admitted markets. New: **L330** — skip observe-sim AI accumulate when the memo
has zero filing bodies (library only; not live FTSE).

## Stale generated artifacts (do not hand-edit)

- `docs/data/progress_report.md` (2026-09-02) — refresh with `ftse-progress-report build --write` on Sunday publish.
- `docs/data/horizon_scan.md` — still describes `research_all_graduated=true`; policy is `false`. Next monthly horizon pass should pick that up.

## What this pass changed in code

1. Sunday ingest cap = weekday full buy-tier (L123).
2. Publish `interim_eps_decline_pct` and `adjusted_eps_growth_pct` on `CompanyReport`.
3. Persist overlay/EPS columns on run snapshots.
4. Ingest-utilization body-path resolver matches filings lookup (absolute, `bodies/<name>`, nested relative).
5. System-gaps `thin_memo_counted_as_coverage` no longer hides behind `executed==0`.
