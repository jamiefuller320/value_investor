#!/usr/bin/env bash
# Retry `pip install` for transient PyPI / empty-index flakes.
# The 2026-09-03 euro-ingest-loop failure died on:
#   No matching distribution found for pandas>=2.2 (from versions: none)
# pip's own --retries covers HTTP download errors, not an empty index listing.
#
# Usage: bash scripts/gha_pip_install.sh [pip-install-args...]
# Env:   PIP_BIN (default pip), PIP_INSTALL_ATTEMPTS (default 4),
#        PIP_INSTALL_SLEEP_BASE (default 4 seconds)
set -euo pipefail

if [ "$#" -eq 0 ]; then
  echo "usage: $0 <pip install args>" >&2
  exit 2
fi

PIP_BIN="${PIP_BIN:-pip}"
MAX_ATTEMPTS="${PIP_INSTALL_ATTEMPTS:-4}"
SLEEP_BASE="${PIP_INSTALL_SLEEP_BASE:-4}"

attempt=1
while [ "$attempt" -le "$MAX_ATTEMPTS" ]; do
  echo "pip install attempt $attempt/$MAX_ATTEMPTS: $PIP_BIN install $*"
  if "$PIP_BIN" install "$@"; then
    echo "pip install succeeded on attempt $attempt"
    exit 0
  fi
  if [ "$attempt" -eq "$MAX_ATTEMPTS" ]; then
    echo "pip install failed after $MAX_ATTEMPTS attempts" >&2
    exit 1
  fi
  delay=$((SLEEP_BASE * attempt))
  echo "pip install failed (attempt $attempt/$MAX_ATTEMPTS); retrying in ${delay}s" >&2
  sleep "$delay"
  attempt=$((attempt + 1))
done
