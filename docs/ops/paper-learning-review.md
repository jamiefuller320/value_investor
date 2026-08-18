# Paper learning churn review (optional)

Observe-only agent synthesis over **`learning_tracks_churn_health.json`** and paper
learning-track artifacts. Does **not** apply decision-review knobs, change paper
books, or open engineering PRs automatically.

Disable before live capital cutover:

```json
// docs/data/paper_automation/review_policy.json
{ "paper_learning_review": { "enabled": false } }
```

## Layered stack

| Layer | Artifact | When |
|-------|----------|------|
| Deterministic rollup | `learning_tracks_churn_health.json` | After weekday `ftse-decision-review --tracks all` |
| Buffered-hold counterfactual | `buffered_hold_counterfactual.json` | After weekday `ftse-decision-review --tracks all` |
| Rule-based knobs | `decision_review.json` | Weekday paper-auto (`--apply`) |
| Broad modelling review | `analysis_review.md` | Sunday `analysis-review.yml` (includes `churn_health` in payload) |
| **This module** | `paper_learning_review.md` | Sunday `paper-learning-review.yml` (if enabled) |

## When it runs

| Trigger | Schedule |
|---------|----------|
| **cron-job.org (primary)** | Sunday **10:45 UTC** (`45 10 * * 0`) |
| GitHub cron (backup) | Sunday 10:45 UTC |
| Manual | Actions → **FTSE Paper Learning Review** |

Runs **after** paper-auto + decision-review have refreshed churn health (weekday)
and ideally after the Sunday analysis bundle; schedule is 10 minutes after analysis review.

## Artifacts

| File | Purpose |
|------|---------|
| `docs/data/paper_automation/learning_tracks_churn_health.json` | Deterministic cost/churn metrics per track |
| `docs/data/paper_automation/buffered_hold_counterfactual.json` | Observe-only exit_confirm_screens 1 vs 2 replay per track |
| `docs/data/paper_automation/review_policy.json` | Kill switch (`paper_learning_review.enabled`) |
| `docs/data/paper_learning_review.md` | Human-readable churn synthesis |
| `docs/data/paper_learning_review.json` | Structured sections |
| `docs/data/paper_learning_tasks.json` | Proposed experiments (`status: proposed`) |

## Commands

```bash
ftse-paper-learning-review status
ftse-paper-learning-review payload --json
ftse-paper-learning-review run          # requires CURSOR_API_KEY + enabled policy
ftse-paper-learning-review list
```

## Enacting proposed experiments

Same manual gates as [analysis-review.md](analysis-review.md):

| Area | Enactment |
|------|-----------|
| `paper_churn` | Edit track `config.json` guards (`exit_confirm_screens`, `min_rebalance_notional_gbp`, …) |
| `paper_knobs` | Manual decision-review probe / config edit — **no** `ftse-analysis-review promote` |
| `offline_sim` | Counterfactual `ftse-sim` / replay runs |

Tasks are **not** copied to `engineering_tasks.json` unless you manually create an engineering task.

## Guardrails

- No `decision-review --apply` from this workflow
- No edits to `paper_fund` / `paper_automation` execution paths
- Agent proposes; humans enact (N24)

See also: [decision-review.md](decision-review.md), [primary-learning-track.md](primary-learning-track.md).
