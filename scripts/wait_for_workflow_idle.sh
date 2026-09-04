#!/usr/bin/env bash
# Wait until listed GitHub Actions workflows have no queued/in-progress runs.
# Usage: wait_for_workflow_idle.sh euro-ingest-loop.yml [library-ingest-sprint.yml ...]
#
# Env: MAX_WAIT_SECONDS (default 2400), POLL_SECONDS (default 60),
# GITHUB_REPOSITORY, GITHUB_TOKEN / GH_TOKEN.
set -euo pipefail

if [ "$#" -lt 1 ]; then
  echo "Usage: $0 <workflow.yml> [workflow.yml ...]" >&2
  exit 2
fi

MAX_WAIT="${MAX_WAIT_SECONDS:-2400}"
POLL="${POLL_SECONDS:-60}"
REPO="${GITHUB_REPOSITORY:-}"

if [ -z "$REPO" ] || ! command -v gh >/dev/null 2>&1; then
  echo "wait_for_workflow_idle: gh or GITHUB_REPOSITORY missing — continuing" >&2
  exit 0
fi
if [ -z "${GH_TOKEN:-}${GITHUB_TOKEN:-}" ]; then
  echo "wait_for_workflow_idle: no token — continuing" >&2
  exit 0
fi
export GH_TOKEN="${GH_TOKEN:-$GITHUB_TOKEN}"

busy_count() {
  local wf="$1"
  local status="$2"
  gh api \
    -H "Accept: application/vnd.github+json" \
    "/repos/${REPO}/actions/workflows/${wf}/runs?status=${status}&per_page=5" \
    --jq '.workflow_runs | length' 2>/dev/null || echo 0
}

workflows_busy() {
  local wf status n
  for wf in "$@"; do
    for status in in_progress queued waiting pending; do
      n="$(busy_count "$wf" "$status")"
      if [ "${n:-0}" -gt 0 ]; then
        echo "$wf $status=$n"
        return 0
      fi
    done
  done
  return 1
}

elapsed=0
while [ "$elapsed" -lt "$MAX_WAIT" ]; do
  if ! busy="$(workflows_busy "$@")"; then
    echo "wait_for_workflow_idle: predecessors idle after ${elapsed}s"
    exit 0
  fi
  echo "wait_for_workflow_idle: busy (${busy}); slept ${elapsed}s / ${MAX_WAIT}s"
  sleep "$POLL"
  elapsed=$((elapsed + POLL))
done

echo "wait_for_workflow_idle: still busy after ${MAX_WAIT}s — skip spare slot" >&2
exit 75
