# Automation Orchestrator — reliable scheduling

GitHub `schedule` triggers are best-effort and have been dropping Sunday/weekday runs. The orchestrator now has layered fallbacks; **enable the external cron once** so Sundays do not depend on manual dispatch.

## What is already in-repo

| Layer | Behaviour |
|-------|-----------|
| Primary schedules | Sun 06:17, daily surplus 05:30, weekdays 08:17 UTC |
| Catch-up schedules | Sun 09:17 + 12:17; weekdays 11:17 UTC |
| Same-day skip | Catch-up does **not** re-run children that already succeeded today |
| Manual / API | `workflow_dispatch` and `repository_dispatch` (`automation-orchestrator`) |

Force a full re-run: Actions UI → Orchestrator → `force=true`, or `FORCE=true` with the script below.

## One-time external cron setup (recommended)

1. Create a GitHub PAT (fine-grained preferred) with **Actions: Read and write** on `jamiefuller320/value_investor` only. Store it as `GH_PAT` in your cron host — never commit it.
2. Add two HTTP cron jobs (cron-job.org, EasyCron, etc.) that call the helper script logic:

**Sunday quiet bundle — 06:20 UTC** (and optional 09:20 backup):

```bash
export GH_PAT=…   # from cron host secret store
export SUITE=sunday
curl -sS -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer $GH_PAT" \
  https://api.github.com/repos/jamiefuller320/value_investor/actions/workflows/automation-orchestrator.yml/dispatches \
  -d '{"ref":"main","inputs":{"suite":"sunday"}}'
```

Or from a checked-out clone:

```bash
GH_PAT=… SUITE=sunday ./scripts/dispatch_orchestrator.sh
```

**Weekday paper — 08:20 UTC Mon–Fri:**

```bash
GH_PAT=… SUITE=weekday_paper ./scripts/dispatch_orchestrator.sh
```

3. Confirm the next window creates an Orchestrator run under
   https://github.com/jamiefuller320/value_investor/actions/workflows/automation-orchestrator.yml
   with event `workflow_dispatch` (external) or `schedule` (GitHub).

### `repository_dispatch` alternative

Some hosts prefer a single repo endpoint:

```bash
MODE=repository_dispatch SUITE=sunday GH_PAT=… ./scripts/dispatch_orchestrator.sh
```

Payload type must be `automation-orchestrator`.

## Verify after a quiet Sunday

```bash
gh run list --workflow=automation-orchestrator.yml --limit 5
gh run list --workflow=library-grow.yml --limit 3
gh run list --workflow=email-report.yml --limit 3
```

Expect at least one successful Sunday suite without a human clicking **Run workflow**.
