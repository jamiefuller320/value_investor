# So-what gap closure

Periodic honest status for screen / ops findings, with an explicit **so what?**
and an automatic gap-closure path when there is little or no fix/no-fix judgment.

## Why

Issues like FCF basis mismatches (Yahoo TTM vs filing-aligned) should not wait for
a human to notice and prompt a fix when the answer is already decided by policy:
fail closed, overlay the signal, queue engineering work. Human judgment stays
only where it belongs (which policy FCF to lock in a bridge).

## Closure classes

| Class | Meaning | Action |
|-------|---------|--------|
| `auto_queue` | No-judgment enforcement gap | Compile an open scoring engineering task (`source=so_what_closure`) |
| `human_gate` | Needs a policy / filing choice | Surface in progress report; existing FCF bridge checklist |
| `observe` | Mild / non-actionable | Report only |

First detector: buy-tier names in `docs/data/latest.json` with material screen vs
filing FCF divergence (≥25%) or FCF action-note markers, without
`fcf_basis_overlay` and/or without a resolved `fcf_bridge.json`.

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
| **Sunday / ad hoc progress report** | Automation + human | Honest status + so-what section; human still reviews bridges |
| **Engineering queue** | Automation | Picks up `source=so_what_closure` tasks like any other open scoring task |

## Artifacts

| File | Role |
|------|------|
| `docs/data/so_what_closure.json` | Last apply/scan snapshot (counts, findings, created tasks) |
| `docs/data/engineering_tasks.json` | Receives auto_queue tasks |
| `docs/data/progress_report.md` | Includes So what? section |

## What stays human

Writing `docs/data/research/<TICKER>/sources/fcf_bridge.json` (which policy FCF)
remains a human gate — see [fcf-basis-bridges.md](fcf-basis-bridges.md). So-what
surfaces those gates; it does not invent policy FCF numbers.

Analysis-review experiment promotion stays human for the same reason: judgment.

## Related

- [progress-report.md](progress-report.md)
- [ops-monitor.md](ops-monitor.md)
- [fcf-basis-bridges.md](fcf-basis-bridges.md)
- [ops-review-cadence.md](ops-review-cadence.md)
