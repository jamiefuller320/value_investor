#!/usr/bin/env bash
# Resolve a user PAT for workflow_dispatch (shared by dispatch_*.sh scripts).
#
# Prefers WORKFLOW_DISPATCH_PAT over GH_PAT. Rejects ghs_ integration tokens
# (Cursor/GitHub App) with a clear error.
#
# Usage:
#   source "$(dirname "$0")/resolve_workflow_pat.sh"
#   WORKFLOW_PAT="$(resolve_workflow_pat)" || exit 1

resolve_workflow_pat() {
  local pat=""
  if [[ -n "${WORKFLOW_DISPATCH_PAT:-}" ]]; then
    pat="${WORKFLOW_DISPATCH_PAT}"
  elif [[ -n "${GH_PAT:-}" ]]; then
    pat="${GH_PAT}"
  fi

  if [[ -z "${pat}" ]]; then
    echo "WORKFLOW_DISPATCH_PAT or GH_PAT is required (fine-grained PAT with Actions: Read and write on the repo)" >&2
    return 1
  fi

  if [[ "${pat}" == ghs_* ]]; then
    echo "Configured token is a GitHub App integration token (ghs_…), not a user PAT." >&2
    echo "Set WORKFLOW_DISPATCH_PAT to a fine-grained PAT with Actions: Read and write." >&2
    return 1
  fi

  printf '%s' "${pat}"
}
