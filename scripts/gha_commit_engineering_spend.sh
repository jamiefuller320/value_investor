#!/usr/bin/env bash
# Commit engineering-agent ad-hoc spend to main with fetch + retry.
#
# Parallel engineering-agent runs (max_parallel=2) plus ingest/queue jobs all
# push policy.json to main. git-auto-commit-action loses that race and fails
# the job *after* the agent finished, so no PR opens and ops flags
# "Engineering agent sync failures".
#
# Re-apply the increment on origin/main each attempt so two agents cannot
# clobber each other's spend counters (or other policy fields).
#
# Usage: bash scripts/gha_commit_engineering_spend.sh
# Env:   GHA_COMMIT_ATTEMPTS (default 5)
#        GHA_COMMIT_SLEEP_BASE (default 3)
#        RECORD_SPEND_CMD (default: ftse-engineering record-spend --json)

set -euo pipefail

POLICY="${POLICY_PATH:-docs/data/library/policy.json}"
MAX_ATTEMPTS="${GHA_COMMIT_ATTEMPTS:-5}"
SLEEP_BASE="${GHA_COMMIT_SLEEP_BASE:-3}"
RECORD_SPEND_CMD="${RECORD_SPEND_CMD:-ftse-engineering record-spend --json}"
COMMIT_MESSAGE="${COMMIT_MESSAGE:-chore: record engineering agent spend [skip ci]}"

# Agent deliverables live under src/, tests/, output/. docs/data/ is operational
# (ingest-loop, queue UI, policy spend) and must not ride the agent stash — a
# concurrent ingest push makes stash pop leave ingest_discovery* in "needs merge"
# and the next "Create feature branch" checkout aborts.
ENG_AGENT_WORK_PATHS=(src/ tests/ output/)

git_clean_state() {
  git merge --abort 2>/dev/null || true
  git rebase --abort 2>/dev/null || true
  if [ -n "$(git diff --name-only --diff-filter=U 2>/dev/null || true)" ]; then
    git reset --hard HEAD
  fi
}

stash_ref_for_label() {
  local label="$1"
  git stash list --format='%gd %s' | awk -v label="$label" 'index($0, label) { print $1; exit }'
}

working_tree_dirty() {
  [ -n "$(git status --porcelain 2>/dev/null || true)" ]
}

drop_operational_docs_data() {
  if git rev-parse --verify HEAD >/dev/null 2>&1; then
    git checkout HEAD -- docs/data/ 2>/dev/null || true
  fi
}

restore_agent_work() {
  local ref="$1"
  if [ -z "$ref" ]; then
    return 0
  fi

  git_clean_state
  drop_operational_docs_data

  if git stash apply "$ref"; then
    drop_operational_docs_data
    git checkout HEAD -- "$POLICY" 2>/dev/null || true
    git stash drop "$ref" 2>/dev/null || true
    return 0
  fi

  echo "stash apply had conflicts — restoring agent paths only" >&2
  git_clean_state
  drop_operational_docs_data
  local prefix
  for prefix in "${ENG_AGENT_WORK_PATHS[@]}"; do
    if [ -e "$prefix" ] || git ls-tree -d HEAD "$prefix" >/dev/null 2>&1; then
      git checkout "$ref" -- "$prefix" 2>/dev/null || true
    fi
  done
  drop_operational_docs_data
  git checkout HEAD -- "$POLICY" 2>/dev/null || true
  git stash drop "$ref" 2>/dev/null || true
}

STASH_LABEL="eng-agent-work-$(date +%s)"
STASH_REF=""

if working_tree_dirty; then
  # Drop the increment from the agent run step; each retry re-applies it on
  # the latest origin/main policy so concurrent spend/policy edits are not
  # overwritten by a stale working-tree copy.
  if [ -e "$POLICY" ]; then
    git checkout -- "$POLICY" 2>/dev/null || true
  fi
  drop_operational_docs_data
  if working_tree_dirty; then
    git stash push -u -m "$STASH_LABEL"
    STASH_REF="$(stash_ref_for_label "$STASH_LABEL")"
  fi
fi

attempt=1
while [ "$attempt" -le "$MAX_ATTEMPTS" ]; do
  echo "Spend commit attempt $attempt/$MAX_ATTEMPTS"
  git fetch origin main
  git checkout -B main origin/main

  # shellcheck disable=SC2086
  eval "$RECORD_SPEND_CMD"

  git add -- "$POLICY"
  if git diff --cached --quiet; then
    echo "No policy.json spend delta after re-record"
    restore_agent_work "$STASH_REF"
    exit 0
  fi

  git commit -m "$COMMIT_MESSAGE"
  if git push origin HEAD:main; then
    echo "Engineering spend committed to main on attempt $attempt"
    restore_agent_work "$STASH_REF"
    exit 0
  fi

  echo "Spend push rejected (attempt $attempt/$MAX_ATTEMPTS); retrying" >&2
  git reset --hard origin/main
  if [ "$attempt" -eq "$MAX_ATTEMPTS" ]; then
    break
  fi
  delay=$((SLEEP_BASE * attempt))
  echo "Retrying in ${delay}s…" >&2
  sleep "$delay"
  attempt=$((attempt + 1))
done

echo "::warning::Could not push engineering spend to main after $MAX_ATTEMPTS attempts; continuing so the engineering PR can still open" >&2
restore_agent_work "$STASH_REF"
exit 1
