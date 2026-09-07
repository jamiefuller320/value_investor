#!/usr/bin/env bash
# Dispatch pages.yml after a [skip ci] docs commit so the live dashboard
# picks up sidecar JSON (market_status, automation, latest).
set -euo pipefail

if [ -z "${GITHUB_ACTIONS:-}" ]; then
  echo "pages dispatch skipped (not GitHub Actions)"
  exit 0
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "pages dispatch skipped (gh not available)"
  exit 0
fi

gh workflow run pages.yml
echo "Dispatched pages.yml after dashboard data commit"
