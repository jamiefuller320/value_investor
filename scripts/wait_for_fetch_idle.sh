#!/usr/bin/env bash
# Wait until euro and stream 1 are not actually fetching.
#
# Usage: wait_for_fetch_idle.sh euro-ingest-loop.yml library-ingest-sprint.yml
#
# Only in-progress runs are inspected. A later wave that is merely queued,
# waiting, or pending is not a reason to keep stream 2 standing. The wait
# still runs to MAX_WAIT_SECONDS while a current run is fetching.
#
# Exit 0 when clear. Exit 75 when the cap is hit and a run is still fetching.
# A GitHub API failure counts as fetching (fail closed) until that cap.
# Missing gh or token continues, matching wait_for_workflow_idle.sh.
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
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"

if [ -z "$REPO" ] || ! command -v gh >/dev/null 2>&1; then
  echo "wait_for_fetch_idle: gh or GITHUB_REPOSITORY missing — continuing" >&2
  exit 0
fi
if [ -z "${GH_TOKEN:-}${GITHUB_TOKEN:-}" ]; then
  echo "wait_for_fetch_idle: no token — continuing" >&2
  exit 0
fi
export GH_TOKEN="${GH_TOKEN:-$GITHUB_TOKEN}"

run_ids() {
  local wf="$1"
  local raw
  if ! raw="$(gh api "/repos/${REPO}/actions/workflows/${wf}/runs?status=in_progress&per_page=5" 2>/dev/null)"; then
    echo "API_FAIL"
    return 0
  fi
  RAW="$raw" python3 - <<'PY'
import json
import os
import sys

raw = os.environ.get("RAW") or ""
try:
    payload = json.loads(raw)
except json.JSONDecodeError:
    print("API_FAIL")
    sys.exit(0)
if not isinstance(payload, dict):
    print("API_FAIL")
    sys.exit(0)
for run in payload.get("workflow_runs") or []:
    if isinstance(run, dict) and run.get("id") is not None:
        print(run["id"])
PY
}

run_is_fetching() {
  local wf="$1"
  local run_id="$2"
  local jobs
  if ! jobs="$(gh api "/repos/${REPO}/actions/runs/${run_id}/jobs?per_page=20" 2>/dev/null)"; then
    return 0
  fi
  if printf '%s' "$jobs" | python3 -m value_investor.ingest_fetch_idle --decide --workflow "$wf"; then
    return 0
  fi
  return 1
}

workflows_fetching() {
  local wf ids id
  for wf in "$@"; do
    ids="$(run_ids "$wf")"
    if [ "$ids" = "API_FAIL" ]; then
      echo "$wf api_fail"
      return 0
    fi
    while IFS= read -r id; do
      [ -z "$id" ] && continue
      if run_is_fetching "$wf" "$id"; then
        echo "$wf run ${id} fetching"
        return 0
      fi
    done <<< "$ids"
  done
  return 1
}

elapsed=0
while [ "$elapsed" -lt "$MAX_WAIT" ]; do
  if ! busy="$(workflows_fetching "$@")"; then
    echo "wait_for_fetch_idle: predecessors not fetching after ${elapsed}s"
    exit 0
  fi
  echo "wait_for_fetch_idle: busy (${busy}); slept ${elapsed}s / ${MAX_WAIT}s"
  sleep "$POLL"
  elapsed=$((elapsed + POLL))
done

echo "wait_for_fetch_idle: still fetching after ${MAX_WAIT}s — skip spare slot" >&2
exit 75
