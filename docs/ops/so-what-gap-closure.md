# So-what gap closure

Periodic honest status for screen / ops findings, with an explicit **so what?**
and an automatic gap-closure path when there is little or no fix/no-fix judgment.

## Why

Issues like FCF basis mismatches (Yahoo TTM vs filing-aligned) should not wait for
a human to notice and prompt a fix when the answer is already decided by policy:
fail closed, overlay the signal, lock policy FCF via majority / filing fallback,
queue engineering work when enforcement is missing. Human judgment stays only for
residual overrides (auto pick wrong, or no filing/company figure).

## Closure classes

| Class | Meaning | Action |
|-------|---------|--------|
| `auto_queue` | No-judgment enforcement gap | Compile an open scoring engineering task (`source=so_what_closure`) |
| `human_gate` | Residual: cannot auto-resolve policy FCF | Surface in progress report; optional bridge override |
| `observe` | Mild / non-actionable | Report only |

First detector: buy-tier names in `docs/data/latest.json` with material screen vs
filing FCF divergence (≥25%) or FCF action-note markers, without
`fcf_basis_overlay`. Policy FCF no longer requires a human bridge when
filing-aligned or company-adjusted is present — see [fcf-basis-bridges.md](fcf-basis-bridges.md).

## Commands

```bash
# Classify only (no queue writes)
ftse-progress-report so-what

# Preview tasks that would be queued
ftse-progress-report so-what --dry-run

# Queue auto_queue findings into docs/data/engineering_tasks.json
ftse-progress-report so-what --apply

# Progress report includes a So what? section (read-only classify)
ftse-progress-report build
ftse-progress-report build --write
```

## Cadence

| Cadence | Who | Behaviour |
|---------|-----|-----------|
| **Daily ops monitor** | Automation | When `--apply` / CI default: run so-what auto-queue after other drafts |
| **Sunday / ad hoc progress report** | Automation + human | Honest status + so-what section; residual bridge overrides only |
| **Engineering queue** | Automation | Picks up `source=so_what_closure` tasks like any other open scoring task |

## Artifacts

| File | Role |
|------|------|
| `docs/data/so_what_closure.json` | Last apply/scan snapshot (counts, findings, created tasks) |
| `docs/data/engineering_tasks.json` | Receives auto_queue tasks |
| `docs/data/progress_report.md` | Includes So what? section |

## What stays human

- Optional override of auto FCF policy via `fcf_bridge.json` when majority/filing is wrong — see [fcf-basis-bridges.md](fcf-basis-bridges.md).
- Analysis-review experiment promotion (judgment).

## Related

- [progress-report.md](progress-report.md)
- [ops-monitor.md](ops-monitor.md)
- [fcf-basis-bridges.md](fcf-basis-bridges.md)
- [ops-review-cadence.md](ops-review-cadence.md)

## Dashboard

Overview → Progress report → **So what? — needs your judgment** lists live `human_gate` items. Auto-queue counts are informational; engineering picks those up from the queue.
