# GitHub Actions secret hygiene

This repo is **public**. Any `workflow_run` job runs in the base-repo context and
receives the default `GITHUB_TOKEN` (and repository secrets when configured). Treat
PR head branch names and fork commits as **untrusted input**.

## High-risk patterns (blocked)

| Pattern | Risk | Mitigation in this repo |
|---------|------|-------------------------|
| `workflow_run` after PR CI, then `${{ github.event.workflow_run.head_branch }}` inside `run:` | Shell injection → token / secret theft | Pass via `env:` + strict regex; never `${{ }}` into the script body |
| `workflow_run` autofix that `pip install -e .` from the PR ref | Malicious `pyproject` / package code runs with write token | Install **non-editable** package from `main`, copy trusted scripts to `/tmp`, then check out the PR SHA |
| `workflow_run` without a same-repo gate | Public **fork** PRs trigger privileged jobs | Require `head_repository.full_name == github.repository` |
| Logging full API keys | Key leak via Actions logs | Use `api_key_fingerprint()` / env status helpers only |
| `${{ github.event.inputs.* }}` inside `run:` (string dispatch inputs) | Shell / Python injection → secret theft if a write collaborator or stolen `WORKFLOW_DISPATCH_PAT` can dispatch | Pass all inputs via `env:` + allowlists; never `${{ }}` into the script body |

## Workflows that must stay gated

- `ci-pr-autofix.yml` — same-repo + `cursor/*` regex + trusted install from `main`
- `engineering-auto-merge.yml` — same-repo + `cursor/eng-YYYYMMDD-NN-1de3` regex
- `engineering-queue.yml` — PR head ref only via `env:` after regex gate

`CURSOR_API_KEY` / `CURSOR_API_KEY_V2` themselves are only injected into schedule /
`workflow_dispatch` jobs that check out `main` (or the dispatch ref). The outsider
path to those secrets is **indirect**: steal a write-capable `GITHUB_TOKEN` from a
`workflow_run` job, push a malicious workflow, then wait for the next schedule that
loads the Cursor key.

## Which secret workflows use

Agent workflows inject both secrets and prefer V2:

```yaml
CURSOR_API_KEY_V2: ${{ secrets.CURSOR_API_KEY_V2 }}
CURSOR_API_KEY: ${{ secrets.CURSOR_API_KEY_V2 || secrets.CURSOR_API_KEY }}
```

Local / Cloud CLIs already resolve `CURSOR_API_KEY_V2` first via `resolve_cursor_api_key()`.
Keep **GitHub Actions** `CURSOR_API_KEY_V2` (or `CURSOR_API_KEY`) equal to a **valid**
User API key from the Cursor dashboard. A set-but-dead legacy `CURSOR_API_KEY` alone
still fails authentication even though preflight only checks “non-empty”.

## Automated daily check

`gha-secret-hygiene.yml` runs:

1. **Daily** (~06:20 UTC via cron-job.org `workflow_dispatch`, GitHub `schedule` as backup)
2. **On PRs / pushes** that touch `.github/workflows/**` or the scanner itself
3. **Manual** `workflow_dispatch` with optional `force=true`

The daily job **skips** when no PRs were merged to `main` and no commits touched
`.github/workflows/` in the last **36 hours** (override with `force`). That keeps
noise low while still catching workflow changes introduced by merges.

Local / CI commands:

```bash
ftse-gha-secret-hygiene check
ftse-gha-secret-hygiene schedule-gate --force
pytest -q tests/test_gha_secret_hygiene.py
```

Failures on `main` draft a supervised engineering task via `workflow-failure-responder`.

## If `CURSOR_API_KEY` may already be compromised

1. Revoke the key at [Cursor API keys](https://cursor.com/dashboard/api-keys).
2. Create a new key; update GitHub Actions secrets `CURSOR_API_KEY_V2` **and**
   `CURSOR_API_KEY` (and any Cursor Cloud / cron host copies) to the new value.
3. Review recent Actions runs for unexpected `workflow_run` jobs on odd `cursor/*` branch names.
4. Confirm `main` workflow files were not modified by an unexpected actor.
5. Prefer branch protection on `main` (required reviews / block GITHUB_TOKEN force-push) so a stolen Actions token cannot silently plant a secret-exfiltrating workflow.

## `workflow_dispatch` inputs and PAT blast radius

`WORKFLOW_DISPATCH_PAT` / cron-job.org do **not** store SMTP / AWS / Cursor secrets, but a
stolen dispatch PAT can start any `workflow_dispatch` job that loads them. Free-form
string inputs (`pin_ticker`, `task_id`, `markets`, …) interpolated with `${{ }}` into
`run:` enable shell injection in those jobs (and cross-step `GITHUB_PATH` poisoning into
later secret-bearing steps).

Hardening rule: put every `github.event.inputs.*` value into `env:`, quote it in the
shell, and allowlist free-form strings with a strict regex before use. The daily
`ftse-gha-secret-hygiene` scan fails on `dispatch_input_in_run`.

## Related

- [ci-fix-automation.md](ci-fix-automation.md) — PR autofix / auto-merge flow
- [engineering-sync.md](engineering-sync.md) — `WORKFLOW_DISPATCH_PAT` scope
