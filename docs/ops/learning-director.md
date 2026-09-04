# Learning Director (weekly)

Read-only **orchestration layer** that runs after analysis-review and
paper-learning-review each Sunday. Synthesises regime checks, convergence
narrative, experiment inventory, and **vision roadmap activation proposals**.

Does **not** apply knobs, mutate screens, spawn tracks, or open engineering PRs.
Scoring / assessment-model experiments stay in [analysis-review.md](analysis-review.md);
churn experiments stay in [paper-learning-review.md](paper-learning-review.md). The
director only checks that trajectory / exclusion / exit-timing triggers were turned into
those specialist experiments — prefer thin `[analysis]` / `[monitoring]` follow-ups over
a second experiment queue. The payload includes `system_gaps` (same snapshot as
analysis-review). If a high-severity flag exists and analysis-review did not name it,
propose a thin `[ops]` / `[research]` follow-up — do not treat unused `weekly_ops` or
memo-file coverage as proof the learning consumer is fed. See
[learning-director-vision.md](learning-director-vision.md#discrete-specialist-pipelines-director-as-oversight)
and [analysis-review.md](analysis-review.md#system-gaps-learning-path-integrity).

Vision doc: [learning-director-vision.md](learning-director-vision.md) ·
structured roadmap: [`docs/data/learning_director_vision.json`](../data/learning_director_vision.json).

## Commands

```bash
# Enable flag and artifact paths
ftse-learning-director status

# Build agent payload (no API call)
ftse-learning-director payload --json

# Run agent synthesis (requires CURSOR_API_KEY)
ftse-learning-director run

# Compile tasks from a saved review markdown
ftse-learning-director compile docs/data/learning_director_review.md

# Skip fragment compile on run (tasks only)
ftse-learning-director run --no-compile-fragments

# List proposed tasks
ftse-learning-director list
```

## Artifacts

| File | Purpose |
|------|---------|
| `docs/data/learning_director_review.json` | Structured sections from latest run |
| `docs/data/learning_director_review.md` | Human-readable review |
| `docs/data/learning_director_tasks.json` | Proposed actions (status=proposed) |
| `docs/deferred-ideas.json` | HORIZON FRAGMENTS appended via `ftse-defer fragment` |
| `output/learning_director_payload.json` | Agent input snapshot (local runs) |

## Enable / disable

`docs/data/paper_automation/review_policy.json`:

```json
{
  "learning_director": {
    "enabled": true,
    "cadence": "weekly"
  }
}
```

Set `enabled: false` before live capital cutover.

## Weekly schedule

GitHub Actions: `.github/workflows/learning-director-review.yml` — Sunday **10:55 UTC**
(after paper-learning-review at 10:45).

## Human gate

The director reads `learning_director_vision.json` and recommends **ACTIVATE / HOLD /
RETIRE** for each roadmap phase, citing `revisit_when` triggers. Activation is
**proposal-only** — acknowledge in weekly ops review before building.

Cadence context: [ops-review-cadence.md](ops-review-cadence.md).
