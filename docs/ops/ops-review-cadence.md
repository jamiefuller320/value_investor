# Ops review cadence (unified anchor)

One calendar for the three human review loops. Individual runbooks stay
authoritative for commands and artifacts; this page is the sequence and owner
map (L124 / frag-20260811-08).

## Sequence

| Cadence | When (UTC) | Human job | Primary artifacts | Runbook |
|---------|------------|-----------|-------------------|---------|
| **Weekly** | Sunday after email quiet bundle (~10:35) | Read analysis review; triage experiments; knob-calibration gates | `docs/data/analysis_review.md`, `analysis_tasks.json`, `knob_calibration_priors.json` | [analysis-review.md](analysis-review.md) · [knob-calibration.md](knob-calibration.md) |
| **Monthly** | First Sunday **11:00** (after weekly when possible) | Horizon scan; triage open `ftse-defer` fragments / ACCELERATE | `docs/data/horizon_scan.md`, `horizon_scan.json`, `horizon_tasks.json` | [horizon-scan.md](horizon-scan.md) |
| **Quarterly** | Calendar quarter review | Deferred ideas pass (`ftse-defer status` done/drop/now) | `docs/deferred-review.md`, `docs/deferred-ideas.json` | [deferred-review.md](../deferred-review.md) |

Weekday paper-auto + decision-review are **automated**; still spot-check learning
tracks on the Automation tab — see [human-tasks-checklist.md](human-tasks-checklist.md).

## Owner defaults

| Loop | Owner | Notes |
|------|-------|-------|
| Weekly analysis / knobs | Human (portfolio operator) | Do not promote knobs until shadow gates pass |
| Monthly horizon | Human | Observe-only for paper books; promote ACCELERATE manually |
| Quarterly deferred | Human | Prefer `ftse-defer` CLI over hand-editing JSON |

## Related automation (do not duplicate)

| Automation | Cadence | Doc |
|------------|---------|-----|
| Paper-auto + decision-review | Weekday | [decision-review.md](decision-review.md) |
| Email / deep analysis / gap-fill | Sunday quiet | [orchestrator-cron.md](orchestrator-cron.md) |
| Engineering queue / eng-idle ingest | Hourly weekdays | [engineering-sync.md](engineering-sync.md) · [horizon-scan.md](horizon-scan.md#ingest-gap-closure-runs) |

## Checklist registration

Human gates for this cadence live in
[`docs/human_tasks_checklist.json`](../human_tasks_checklist.json) and
[human-tasks-checklist.md](human-tasks-checklist.md) (dashboard Automation →
Human tasks).
