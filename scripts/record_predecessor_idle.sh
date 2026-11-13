#!/usr/bin/env bash
# Record whether predecessor workflows are idle on GITHUB_OUTPUT.
#
# Usage: record_predecessor_idle.sh <skip-message> <workflow.yml> [workflow.yml ...]
#
# idle=true and exit 0 when the predecessors are idle.
# idle=false and exit 0 when they stay queued or running (wait exit 75).
# Any other wait failure is propagated. Do not read $? after an if: a failed
# condition with no else branch returns 0, which used to drop exit 75 and leave
# idle unset.
#
# Tests may set PREDECESSOR_WAIT_SCRIPT to a stub of wait_for_workflow_idle.sh.
set -euo pipefail

if [ "$#" -lt 2 ]; then
  echo "Usage: $0 <skip-message> <workflow.yml> [workflow.yml ...]" >&2
  exit 2
fi
if [ -z "${GITHUB_OUTPUT:-}" ]; then
  echo "record_predecessor_idle: GITHUB_OUTPUT is required" >&2
  exit 2
fi

message="$1"
shift
wait_script="${PREDECESSOR_WAIT_SCRIPT:-$(dirname "$0")/wait_for_workflow_idle.sh}"

set +e
bash "$wait_script" "$@"
rc=$?
set -e

if [ "$rc" -eq 0 ]; then
  echo "idle=true" >> "$GITHUB_OUTPUT"
  exit 0
fi
if [ "$rc" -eq 75 ]; then
  echo "idle=false" >> "$GITHUB_OUTPUT"
  echo "$message"
  exit 0
fi
exit "$rc"
