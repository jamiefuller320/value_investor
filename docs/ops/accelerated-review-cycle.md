# Accelerated review cycle (mid-week refresh)

Manual runbook for closing the **Sunday compile → weekday engineering → fresh analysis**
loop in the same calendar week, instead of waiting for the next Sunday email bundle.

Use this when merged engineering changes (ingest, scoring, prompts) should be reflected
on the dashboard **Analysis** tab before the next scheduled Sunday screen.

## What this refreshes

The GitHub Pages **Analysis** tab reads `docs/data/latest.json`:

| UI section | `latest.json` key | Produced by |
|------------|-------------------|-------------|
| Portfolio deep analysis | `deep_analysis` | `email-report` (`--deep-analysis`) |
| Post-run improvement review | `post_run_review` | `email-report` (`--post-run-review`) |
| Strong buy research memos | `research[]` | gap-fill + publish |

`analysis-review.yml` writes `analysis_review.md` / `analysis_tasks.json` — **not**
shown on the Analysis tab, but useful ops synthesis. Run it after the email refresh
when modelling/backtest review should catch up.

Weekday **ingest-loop** (Mon/Wed/Fri) improves filing bodies offline; this runbook
**re-screens and re-publishes** so gap-fill and post-run review see those bodies.

## Rollout plan

| Phase | When | Action |
|-------|------|--------|
| **0 — Baseline** | **Next Sunday cycle** (scheduled engineering-loop test) | Let `SUITE=sunday` run normally. Confirm compile → queue → agent → merge. Do **not** run this runbook yet. |
| **1 — First manual cycle** | **After** Sunday succeeds **and** the weekday engineering queue drains (`open_count=0`, no `pr_open`) | Follow [Procedure](#procedure) below once. Record spend and whether Analysis conclusions changed materially. |
| **2 — Habit or automation** | After Phase 1 succeeds | Repeat manually when needed, **or** rely on **auto-chain** (L97): when an ingest/scoring/prompt/coverage engineering PR merges and the queue idles, `engineering-queue.yml` may dispatch `automation-orchestrator` `suite=email_only` (max **2/week**, `weekly_ops` headroom ≥ ~$18, no active email/orchestrator run). Log: `docs/data/accelerated_review.json`. |

**First planned use:** the week starting **Sunday 2026-08-03** (after the baseline Sunday run completes and engineering tasks from that compile are merged or parked).

## Prerequisites (all must pass)

```bash
ftse-engineering queue-status --json
```

| Check | Required state |
|-------|----------------|
| Engineering queue | `open_count: 0`, `pr_open_count: 0` (or you accept stacking a new batch) |
| Merged code on `main` | Ingest/scoring/prompt fixes you want reflected are merged |
| `weekly_ops` headroom | `estimated_spend_weekly_ops_usd_this_week` in `docs/data/library/policy.json` — leave ~$15–25 for email agents if near the $50 cap |
| No conflicting commits | No other workflow currently committing `docs/data/**` (check Actions) |
| Weekday ingest (optional) | Mon/Wed/Fri ingest-loop succeeded since last Sunday — bodies are fresher |

**Skip** mid-week refresh when:

- Only docs/ops tasks merged (little analysis impact)
- `weekly_ops` is already at cap and you need Sunday ladder headroom
- An engineering PR is still open or agent is running

## Procedure

### 1. Refresh screen + Analysis tab

Prefer **`email_only`** — skips library ladder and model review (saves `weekly_ops`).

```bash
export WORKFLOW_DISPATCH_PAT=…   # or GH_PAT

SUITE=email_only FORCE=true ./scripts/dispatch_orchestrator.sh
```

Or GitHub Actions → **Automation Orchestrator** → `suite=email_only`, `force=true`.

**What runs:** `email-report.yml` → screen → deep analysis → ingest-improvement (cap 15) →
gap-fill → post-run review → engineering compile → publish dashboard → SMTP email.

**Concurrency:** `ftse-email-report` group — only one email run at a time.

### 2. Optional — modelling analysis review

After step 1 commits `docs/data/` (watch `email-report` succeed):

```bash
WORKFLOW=analysis-review.yml \
  INPUTS_JSON='{"force":"true"}' \
  ./scripts/dispatch_github_workflow.sh
```

Same-day skip applies without `force=true`.

### 3. Verify

```bash
# Workflows
gh run list --workflow=email-report.yml --limit 1
gh run list --workflow=analysis-review.yml --limit 1

# Queue after compile
ftse-engineering list

# Dashboard payload
python3 -c "
import json
from pathlib import Path
d = json.loads(Path('docs/data/latest.json').read_text())
print('generated_at', d.get('generated_at'))
print('deep_analysis', bool(d.get('deep_analysis')))
print('post_run_review', bool(d.get('post_run_review')))
print('research memos', len(d.get('research') or []))
"
```

Open the dashboard **Analysis** tab — executive intro, post-run review, and memo
versions should match the new `generated_at`.

### 4. Engineering follow-through

`--compile-engineering-tasks` **merges** new suggestions into
`docs/data/engineering_tasks.json` and preserves `merged` / `pr_open` status on
existing tasks.

Weekday **engineering-queue** (hourly :15 UTC) may dispatch `engineering-agent.yml`
for new `open` tasks unless blocked by ad-hoc spend checkpoint (~$60) or an
in-flight PR.

Review new open tasks:

```bash
ftse-engineering list
gh run list --workflow=engineering-queue.yml --limit 3
```

## Automated mid-week chain (L97)

When an engineering task PR merges on `main` (`cursor/eng-*-1de3` branches), the
**engineering-queue** workflow:

1. Marks the task merged and reconciles queue state.
2. If no further engineering dispatch is needed (`open_count=0`, `pr_open_count=0`).
3. Evaluates guards via `ftse-engineering try-accelerated-email`.
4. On pass: records the run in `docs/data/accelerated_review.json` and dispatches
   `automation-orchestrator.yml` with `suite=email_only`, `force=true`.

Guards (all must pass):

| Guard | Detail |
|-------|--------|
| Queue idle | `open_count=0`, `pr_open_count=0` |
| Material merge | Merged task area ∈ `ingest`, `scoring`, `prompt`, `coverage` |
| Weekday | Skips Sunday (scheduled `SUITE=sunday` handles that) |
| `weekly_ops` headroom | ≥ ~$18 remaining after estimated email_only cost |
| Weekly cap | Max 2 mid-week `email_only` chains per ISO week |
| No active runs | `email-report.yml` and `automation-orchestrator.yml` not in flight |

Manual override remains available via [Procedure](#procedure) step 1.

## Costs and side effects

| Item | Effect |
|------|--------|
| **`weekly_ops` pool** (~$50/week) | Email agents (deep analysis, gap-fill, post-run review) charge here |
| **Engineering ad-hoc pool** (~$60 checkpoint) | Separate; new compile may trigger agent via queue |
| **Second weekly email** | SMTP sends again unless you later add a publish-only mode |
| **`docs/data/history/`** | New `run_*` snapshot — Performance tab overlays shift |
| **Paper books** | Unchanged — re-screen is read-only w.r.t. paper fund |
| **Git races** | Rare if email + analysis-review are serialised; ingest-loop same day may contend on `docs/data/` |

## When to use full `SUITE=sunday` instead

Use full Sunday bundle only when you also want **library ladder** + **model review**:

```bash
SUITE=sunday FORCE=true ./scripts/dispatch_orchestrator.sh
```

Heavier `weekly_ops` burn. For stale Analysis conclusions after engineering merges,
`email_only` is usually enough.

## Related docs

- [orchestrator-cron.md](orchestrator-cron.md) — schedules, PAT, suite matrix
- [analysis-review.md](analysis-review.md) — modelling synthesis (separate from Analysis tab)
- [paper-learning-review.md](paper-learning-review.md) — Sunday churn observe-only review
- Engineering queue — `engineering-queue.yml`, `docs/data/engineering_tasks.json`
