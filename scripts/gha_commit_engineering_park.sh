#!/usr/bin/env bash
# Commit an engineering-agent park onto latest origin/main with fetch + retry.
#
# Preflight / workflow-permission parks previously ran only on the agent
# working tree and exited 1 without pushing — the hourly queue redispatched
# the still-open task and reburned Composer. Re-apply park-task on
# origin/main each attempt so concurrent queue writers cannot drop the park.
#
# Usage:
#   TASK_ID=eng-… PARK_REASON='…' PARKED_POLICY=preflight_clash \
#     bash scripts/gha_commit_engineering_park.sh
# Env:
#   TASK_ID (required)
#   PARK_REASON (required)
#   PARKED_POLICY (default: preflight_clash)
#   GHA_COMMIT_ATTEMPTS (default 5)
#   GHA_COMMIT_SLEEP_BASE (default 3)
#   COMMIT_MESSAGE

set -euo pipefail

TASK_ID="${TASK_ID:?TASK_ID required}"
PARK_REASON="${PARK_REASON:?PARK_REASON required}"
PARKED_POLICY="${PARKED_POLICY:-preflight_clash}"
MAX_ATTEMPTS="${GHA_COMMIT_ATTEMPTS:-5}"
SLEEP_BASE="${GHA_COMMIT_SLEEP_BASE:-3}"
COMMIT_MESSAGE="${COMMIT_MESSAGE:-chore: park engineering task ${TASK_ID} [skip ci]}"
TASKS_PATH="${TASKS_PATH:-docs/data/engineering_tasks.json}"

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
  git stash drop "$ref" 2>/dev/null || true
}

STASH_LABEL="eng-agent-park-$(date +%s)"
STASH_REF=""

if working_tree_dirty; then
  drop_operational_docs_data
  if working_tree_dirty; then
    git stash push -u -m "$STASH_LABEL"
    STASH_REF="$(stash_ref_for_label "$STASH_LABEL")"
  fi
fi

attempt=1
while [ "$attempt" -le "$MAX_ATTEMPTS" ]; do
  echo "Park commit attempt $attempt/$MAX_ATTEMPTS for $TASK_ID"
  git fetch origin main
  git checkout -B main origin/main

  ftse-engineering park-task \
    --task-id "$TASK_ID" \
    --reason "$PARK_REASON" \
    --parked-policy "$PARKED_POLICY"

  git add -- "$TASKS_PATH"
  if git diff --cached --quiet; then
    # Already parked on main (race with traffic PM) — success.
    echo "No engineering_tasks.json park delta after re-park (already parked?)"
    restore_agent_work "$STASH_REF"
    exit 0
  fi

  git commit -m "$COMMIT_MESSAGE"
  if git push origin HEAD:main; then
    echo "Engineering park committed to main on attempt $attempt"
    restore_agent_work "$STASH_REF"
    exit 0
  fi

  echo "Park push rejected (attempt $attempt/$MAX_ATTEMPTS); retrying" >&2
  git reset --hard origin/main
  if [ "$attempt" -eq "$MAX_ATTEMPTS" ]; then
    break
  fi
  delay=$((SLEEP_BASE * attempt))
  echo "Retrying in ${delay}s…" >&2
  sleep "$delay"
  attempt=$((attempt + 1))
done

echo "::error::Could not push engineering park for $TASK_ID after $MAX_ATTEMPTS attempts" >&2
restore_agent_work "$STASH_REF"
exit 1
