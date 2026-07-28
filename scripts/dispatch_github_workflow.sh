#!/usr/bin/env bash
# Dispatch any GitHub Actions workflow via workflow_dispatch (for cron-job.org etc.).
#
# Required:
#   GH_PAT      — PAT with Actions: write on the repo
#   WORKFLOW    — workflow file name (e.g. analysis-review.yml, ingest-loop.yml)
# Optional:
#   REPO        — owner/name (default: jamiefuller320/value_investor)
#   REF         — git ref (default: main)
#   INPUTS_JSON — JSON object for workflow inputs (default: {})
#
# Examples:
#   WORKFLOW=ingest-loop.yml GH_PAT=… ./scripts/dispatch_github_workflow.sh
#   WORKFLOW=analysis-review.yml GH_PAT=… ./scripts/dispatch_github_workflow.sh
#   WORKFLOW=ingest-loop.yml INPUTS_JSON='{"force":"true"}' GH_PAT=… ./scripts/dispatch_github_workflow.sh
set -euo pipefail

REPO="${REPO:-jamiefuller320/value_investor}"
WORKFLOW="${WORKFLOW:?WORKFLOW is required (e.g. analysis-review.yml)}"
REF="${REF:-main}"
INPUTS_JSON="${INPUTS_JSON:-{}}"

if [[ -z "${GH_PAT:-}" ]]; then
  echo "GH_PAT is required (PAT with Actions: write on ${REPO})" >&2
  exit 1
fi

API="https://api.github.com/repos/${REPO}"
AUTH=( -H "Accept: application/vnd.github+json" -H "Authorization: Bearer ${GH_PAT}" )

echo "workflow_dispatch ${WORKFLOW} ref=${REF} inputs=${INPUTS_JSON}"
curl -sS -X POST "${AUTH[@]}" \
  "${API}/actions/workflows/${WORKFLOW}/dispatches" \
  -d "{\"ref\":\"${REF}\",\"inputs\":${INPUTS_JSON}}"

echo
echo "Dispatched. Check: https://github.com/${REPO}/actions/workflows/${WORKFLOW}"
