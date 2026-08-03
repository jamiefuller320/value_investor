# Engineering queue synchronisation

Detects and repairs desync between the engineering queue processor and the
supervised engineering agent.

## Problem this solves

When `engineering-queue.yml` dispatches `engineering-agent.yml` with a concrete
`task_id`, the agent used to run `ftse-engineering compile` unconditionally.
Weekday compiles can mint fresh task ids from stale `output/` artifacts while
dropping still-open tasks from an older run stamp. The agent then failed with
*No open engineering tasks* even though the queue looked healthy.

## Protections

| Layer | Behaviour |
|-------|-----------|
| **Merge guard** | `_merge_task_rows` preserves all `open` tasks, not only terminal/`pr_open` rows |
| **Agent workflow** | Skips compile when `task_id` is provided; resolves stale ids via `resolve_dispatch_task_id` |
| **Queue workflow** | Hourly sync check + re-dispatch when agent failures coincide with open tasks |
| **Ops monitor** | Daily `check_engineering_sync()`; reconciles queue and can dispatch `engineering-queue.yml` |

## CLI / module

```python
from value_investor.engineering_sync import (
    audit_compile_drop_risk,
    resolve_dispatch_task_id,
    run_engineering_sync,
)
```

`audit_compile_drop_risk()` returns open task ids that would disappear if compile
ran against present `output/post_run_review.md` artifacts.

`run_engineering_sync(apply=True)` runs safe queue recovery only — it never
rewrites task payloads or deletes tasks.

## Auto-restart policy

Redispatch happens when **all** of:

1. Open engineering tasks remain
2. No engineering PR is in flight
3. Recent `engineering-agent` failures (6h) **or** compile would drop open tasks

Dispatch target is always re-resolved to a currently open task id.

## Related

- [`ops-monitor.md`](ops-monitor.md) — daily health checks
- [`ci-fix-automation.md`](ci-fix-automation.md) — scoped CI auto-merge loop
