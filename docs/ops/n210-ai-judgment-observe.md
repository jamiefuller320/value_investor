# N210 — fixed-stake AI/filter judgment observe (B3)

**Status:** sealed observe-only **episode walker active** (2026-10-15).  
**registration_id:** `strand-e-ai-judgment-fixed-stake-v0`  
**deferred_id:** `N210`

Owner lock **B3**: judgment evidence for filter-vs-buy-tier lives here as
**fair-cost episode %** (cohort median), not the underpowered 3-name
`ai_judgment_fair` fund NAV. Matched-30 fund twin is a **separate** portfolio
instrument — see [b3-scoreboard-epoch.md](b3-scoreboard-epoch.md). This walker
does **not** freeze, delete, or rewrite matched-30 pots.

## Learning question

On threshold-eligible FTSE names, does the AI/filter identity
(`adjusted_signal` + `research_verdict=accumulate`, `min_conviction=0.6`)
improve fair-cost episode % vs an unfiltered buy-tier draw of the same
eligible set, sized as a fixed-stake mechanical test?

## Spec (v0)

| Knob | Value |
|------|-------|
| Stake | Fixed **100** local |
| Cash / fund NAV | Parked |
| Entry | Progressive — name **newly** clears AI/filter gates (first sighting / re-clear after leave) |
| Exit | **63** trading days **or** identity break (whichever first) |
| Primary metric | Fair-cost episode % (`smooth_ret_cohort_median`) |
| Control | Unfiltered buy-tier cohort median — **report-only** |
| Volume gate | ≥**48** completed **and** ≥**8** calendar weeks |
| Live influence | `influences_live=false` until readiness (**F8**) |
| Competition | **O3 alone-first** — no pairwise crown vs N200/N201 until gates |
| Screen extras | **F4** — reuse existing AI/filter gates; no new extras |
| Launch queue | Waiter — do not steal P1 from holdings / N200 |

## Pipeline status

`pipeline_status: episode_walker_active` — daily refresh walks archived weekly
screens, opens progressive fixed-stake episodes, and persists fair-cost cohort
marks. Do **not** promote or apply knobs from thin medians (**F8**).

## Automation

- **Trigger:** daily ops-monitor `check_n210_ai_judgment_observe`
- **Store:** `docs/data/n210_ai_judgment_observe.json` +
  `docs/data/n210_ai_judgment_registration.json`
- **Queue-health refresh:** projects phase/volume/open/freshness into
  `queue_health.n210_pipeline_health` (no re-score)
- **Findings** (`auto_fixable=False`):
  - **N210 AI-judgment observe refreshed**
  - **N210 volume gate ready for review** (when gate met)
  - **N210 AI-judgment observe failed**
- **CLI:** `ftse-n210-ai-judgment` (ad-hoc drill-down)

## Dashboard

**Analysis → Observe** investment model switcher → **N210 · observe**
(`#analysis/observe/n210`) shows companion diagnostics (time running, volume
toward gate, fair-cost cohort median, open vs completed), its **own**
lifecycle monitor (phase / volume / path + open-or-completed episodes sample +
markers from `n210_ai_judgment_observe.json`), pipeline health, and the alone
path scoreboard. Thin marks (0 completed + open &gt; 0 while walker active)
are honest — not a fail. Not assessment primary; never auto-promote (F8 / B3).

**Automation → Queue & hunter** shows a compact N210 pipeline-health strip
(walker-active + launch-queue waiter badges). Projection helper:
`build_n210_pipeline_health_projection` → `queue_health.n210_pipeline_health`.

## Artifacts

| Path | Role |
|---|---|
| `docs/data/n210_ai_judgment_registration.json` | Frozen seal record |
| `docs/data/n210_ai_judgment_observe.json` | Episode scoreboard + markers + phase/volume |
| `docs/data/queue_health.json` → `n210_pipeline_health` | Dashboard projection (mechanism only) |
| This doc | Runbook |

## Human volume-gate review

When ops marks the volume gate ready: open the observe JSON, read fair-cost
episode % + companions (N toward gate, weeks, buy-tier excess report-only),
and decide only whether a deliberate promotion design is warranted later. Do
**not** promote, do not `decision-review --apply`, and do not open a second
live capital path (**F8**). Do not crown matched-30 from this card.

Checklist: `adhoc-n210-volume-gate-review`.

## Related

- [b3-scoreboard-epoch.md](b3-scoreboard-epoch.md) — freeze/demotion + matched-30
- [fair-cost-primacy.md](fair-cost-primacy.md) — fixed-stake v0
- [n201-value-mom-observe.md](n201-value-mom-observe.md) — template peer
- [assessment-scoreboard.md](assessment-scoreboard.md) — fund product (demoted evidentiary primary)
