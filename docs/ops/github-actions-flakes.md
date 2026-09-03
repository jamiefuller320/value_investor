# GitHub Actions — known flakes and benign cancels

Use this page when failure emails arrive but `main` looks healthy. Most are **infrastructure or concurrency**, not regressions in the repo.

## Quick triage

```bash
# Today's non-success runs
gh api "repos/jamiefuller320/value_investor/actions/runs?per_page=50" \
  | python3 -c "
import json,sys
from datetime import datetime, timezone
today=datetime.now(timezone.utc).strftime('%Y-%m-%d')
for r in json.load(sys.stdin).get('workflow_runs',[]):
    if not r['created_at'].startswith(today): continue
    c=r.get('conclusion') or r.get('status')
    if c not in ('success','skipped'):
        print(c, r['name'], r['html_url'])
"

# Latest main CI + Pages
gh run list --branch main --limit 5
```

If the **latest** `CI` and `Deploy GitHub Pages` runs on `main` are green, older red runs on merged PRs can usually be ignored.

## Known failure patterns

| Pattern | Typical cause | Action needed |
|---------|---------------|---------------|
| `startup_failure` — *"workflow file issue"* | GitHub Actions runner could not start the job (no logs) | **Re-run** or push again; later runs on the same PR usually pass |
| `cancelled` — *"higher priority waiting request"* | `concurrency: cancel-in-progress` on CI when a newer commit lands on the same PR | **None** — superseded run |
| `cancelled` after ~job `timeout-minutes` (no supersede message) | Job hit Actions timeout — often schedule runs omitting `max_runtime_seconds` defaults, or discovery+last ticker overrun past the budget | Ensure workflows always pass an explicit runtime budget; keep `timeout-minutes` > budget + setup + commit (see euro/library ingest workflows) |
| Orchestrator — *"job was not acquired by Runner"* | Hosted runner capacity / queue timeout | **Retry**; Sunday/weekday catch-up schedules or external cron cover missed work (see [orchestrator-cron.md](orchestrator-cron.md)) |
| Ops monitor red on Sunday morning while orchestrator catch-up pending | Primary orchestrator window failed; 07:45 UTC monitor runs before catch-up | **Expected** — monitor still emails `warn`/`fail`; workflow uses `--allow-workflow-stale-exit-zero` so the Actions job stays green when only workflow-overdue findings remain |
| Duplicate orchestrator dispatches same day | Overlapping catch-up + external cron | Orchestrator **gate** job skips when another run is `in_progress`/`queued`; child dispatch uses `busyToday()` (success or active) |
| Node 20 deprecation annotation | Older action major versions on Node 20 runtime | Upgrade `setup-python` → v6, `github-script` → v8 (done in workflow tidy PR) |
| `pip install -e .` — *"No matching distribution found for pandas>=2.2 (from versions: none)"* | Transient PyPI / empty index on one runner (same run's other job can succeed) | Library ingest workflows retry via `scripts/gha_pip_install.sh` (4 attempts, backoff). Re-run if it still fails after retries |
| Euro / library ingest — *local changes to engineering_tasks.json would be overwritten by checkout* | Push script stashed only `docs/data/library/`, leaving `engineering_tasks.json` dirty when origin/main moved | `scripts/push_library_ingest_artifacts.sh` now stashes the full allowlist and restores only files the job changed |

## Examples (2026-07-25)

| Run | Outcome | Notes |
|-----|---------|-------|
| [CI #103](https://github.com/jamiefuller320/value_investor/actions/runs/30158196546) | `startup_failure` | Infra flake; later CI on same branch passed; PR merged |
| [Pages #102 merge](https://github.com/jamiefuller320/value_investor/actions/runs/30157675847) | `startup_failure` | Infra flake; subsequent Pages deploys succeeded |
| [CI #102](https://github.com/jamiefuller320/value_investor/actions/runs/30155950109) | `cancelled` | Superseded by newer push |
| [Orchestrator 2026-07-24](https://github.com/jamiefuller320/value_investor/actions/runs/30108117174) | `failure` (runner acquisition) | Next day's scheduled run succeeded |

## When to investigate further

Treat as a **real** problem when:

- The **latest** `main` CI run fails with pytest errors (not `startup_failure`). CI runs `scripts/check_committed_data_json.py` before pytest to catch merge-conflict markers and invalid JSON in core `docs/data/` files — a common cause of widespread `JSONDecodeError` failures after overlapping automation commits.
- Pages deploy fails on **two consecutive** merges to `main`.
- Orchestrator fails on **both** primary and catch-up windows the same day **and** external cron did not fire.
- A child workflow (`library-grow`, `paper-auto`, `email-report`) fails with application errors in logs.

For application failures, inspect job logs:

```bash
gh run view <run-id> --log-failed
```

## Related

- [orchestrator-cron.md](orchestrator-cron.md) — scheduling, catch-up, external cron
- [ci-fix-automation.md](ci-fix-automation.md) — CI failure → engineering agent → scoped auto-merge
- Workflow definitions: `.github/workflows/`
