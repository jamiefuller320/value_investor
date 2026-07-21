#!/usr/bin/env bash
# Dispatch the Automation Orchestrator via GitHub API (for external cron hosts).
#
# Required:
#   GH_PAT   — fine-grained or classic PAT with Actions: write on this repo
# Optional:
#   REPO     — owner/name (default: jamiefuller320/value_investor)
#   SUITE    — sunday | weekday_paper | surplus_check | catchup_today | … (default: sunday)
#   FORCE    — true to re-run children that already succeeded today (default: false)
#   REF      — git ref to run against (default: main)
#
# Examples:
#   SUITE=sunday ./scripts/dispatch_orchestrator.sh
#   SUITE=weekday_paper ./scripts/dispatch_orchestrator.sh
#   # repository_dispatch alternative (same PAT):
#   MODE=repository_dispatch SUITE=sunday ./scripts/dispatch_orchestrator.sh
set -euo pipefail

REPO="${REPO:-jamiefuller320/value_investor}"
SUITE="${SUITE:-sunday}"
FORCE="${FORCE:-false}"
REF="${REF:-main}"
MODE="${MODE:-workflow_dispatch}"

if [[ -z "${GH_PAT:-}" ]]; then
  echo "GH_PAT is required (PAT with Actions: write on ${REPO})" >&2
  exit 1
fi

API="https://api.github.com/repos/${REPO}"
AUTH=( -H "Accept: application/vnd.github+json" -H "Authorization: Bearer ${GH_PAT}" )

if [[ "${MODE}" == "repository_dispatch" ]]; then
  echo "repository_dispatch automation-orchestrator suite=${SUITE} force=${FORCE}"
  curl -sS -X POST "${AUTH[@]}" \
    "${API}/dispatches" \
    -d "{\"event_type\":\"automation-orchestrator\",\"client_payload\":{\"suite\":\"${SUITE}\",\"force\":${FORCE}}}"
else
  echo "workflow_dispatch automation-orchestrator.yml suite=${SUITE} force=${FORCE} ref=${REF}"
  curl -sS -X POST "${AUTH[@]}" \
    "${API}/actions/workflows/automation-orchestrator.yml/dispatches" \
    -d "{\"ref\":\"${REF}\",\"inputs\":{\"suite\":\"${SUITE}\",\"force\":\"${FORCE}\"}}"
fi

echo
echo "Dispatched. Check: https://github.com/${REPO}/actions/workflows/automation-orchestrator.yml"
