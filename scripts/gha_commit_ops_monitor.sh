#!/usr/bin/env bash
# Commit ops-monitor artifacts onto latest origin/main with push retry.
#
# Status files always overlay (this job owns them). Queue / health / backtest
# files overlay only when origin/main has not changed them since checkout, so a
# raced engineering-queue or ingest commit is not clobbered.
#
# Thin wrapper around scripts/gha_commit_artifacts.sh (L348 shared helper).
#
# Usage: bash scripts/gha_commit_ops_monitor.sh
# Env:   GHA_COMMIT_ATTEMPTS (default 5)
#        GHA_COMMIT_SLEEP_BASE (default 3)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export GHA_COMMIT_OWNED="${GHA_COMMIT_OWNED:-docs/data/ops_status.json docs/data/ops_monitor_log.json}"
export GHA_COMMIT_OPTIONAL="${GHA_COMMIT_OPTIONAL:-docs/data/engineering_tasks.json docs/data/ingest_health_log.json docs/data/backtest_health.json}"
export COMMIT_MESSAGE="${COMMIT_MESSAGE:-chore: ops monitor [skip ci]}"
export GHA_COMMIT_LABEL="${GHA_COMMIT_LABEL:-Ops monitor}"

exec bash "$SCRIPT_DIR/gha_commit_artifacts.sh"
