#!/usr/bin/env bash
# Commit engineering-queue artifacts onto latest origin/main with push retry.
#
# Hourly engineering-queue and post-merge queue updates race with ingest,
# library-grow, and parallel engineering-agent writers on main. A lone
# git pull + git-auto-commit still loses when another push lands between
# rebase and push (2026-09-14 workflow_dispatch failures).
#
# Thin wrapper around scripts/gha_commit_artifacts.sh (L348 shared helper).
#
# Usage:
#   bash scripts/gha_commit_engineering_queue.sh
# Env:
#   COMMIT_MESSAGE         override commit message
#   GHA_COMMIT_OWNED       override owned pathspecs (space-separated)
#   GHA_COMMIT_ATTEMPTS    default 5
#   GHA_COMMIT_SLEEP_BASE  default 3

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export GHA_COMMIT_OWNED="${GHA_COMMIT_OWNED:-docs/data/engineering_tasks.json docs/data/automation.json docs/data/latest.json}"
export COMMIT_MESSAGE="${COMMIT_MESSAGE:-chore: engineering queue recovery [skip ci]}"
export GHA_COMMIT_LABEL="${GHA_COMMIT_LABEL:-Engineering queue}"

exec bash "$SCRIPT_DIR/gha_commit_artifacts.sh"
