#!/usr/bin/env bash
# Commit ops-monitor artifacts onto latest origin/main with push retry.
#
# Status files always overlay (this job owns them). Queue / health / backtest
# files overlay only when origin/main has not changed them since checkout, so a
# raced engineering-queue or ingest commit is not clobbered.
#
# Usage: bash scripts/gha_commit_ops_monitor.sh
# Env:   GHA_COMMIT_ATTEMPTS (default 5)
#        GHA_COMMIT_SLEEP_BASE (default 3)

set -euo pipefail

STATUS_FILES=(
  docs/data/ops_status.json
  docs/data/ops_monitor_log.json
)
OPTIONAL_FILES=(
  docs/data/engineering_tasks.json
  docs/data/ingest_health_log.json
  docs/data/backtest_health.json
)
ALL_FILES=("${STATUS_FILES[@]}" "${OPTIONAL_FILES[@]}")
MAX_ATTEMPTS="${GHA_COMMIT_ATTEMPTS:-5}"
SLEEP_BASE="${GHA_COMMIT_SLEEP_BASE:-3}"
COMMIT_MESSAGE="${COMMIT_MESSAGE:-chore: ops monitor [skip ci]}"

START_SHA="$(git rev-parse HEAD)"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

blob_at() {
  local rev="$1"
  local path="$2"
  git rev-parse "${rev}:${path}" 2>/dev/null || true
}

save_if_exists() {
  local path="$1"
  if [ -f "$path" ]; then
    mkdir -p "$WORKDIR/$(dirname "$path")"
    cp "$path" "$WORKDIR/$path"
  fi
}

restore_file() {
  local path="$1"
  mkdir -p "$(dirname "$path")"
  cp "$WORKDIR/$path" "$path"
}

for path in "${ALL_FILES[@]}"; do
  save_if_exists "$path"
done

git config user.name "${GIT_AUTHOR_NAME:-github-actions[bot]}"
git config user.email "${GIT_AUTHOR_EMAIL:-41898282+github-actions[bot]@users.noreply.github.com}"

attempt=1
while [ "$attempt" -le "$MAX_ATTEMPTS" ]; do
  echo "Ops monitor commit attempt $attempt/$MAX_ATTEMPTS"
  git fetch origin main
  git reset --hard origin/main

  for path in "${STATUS_FILES[@]}"; do
    if [ -f "$WORKDIR/$path" ]; then
      restore_file "$path"
    fi
  done

  for path in "${OPTIONAL_FILES[@]}"; do
    if [ ! -f "$WORKDIR/$path" ]; then
      continue
    fi
    base_blob="$(blob_at "$START_SHA" "$path")"
    main_blob="$(blob_at origin/main "$path")"
    if [ "$base_blob" = "$main_blob" ]; then
      restore_file "$path"
    else
      echo "Skipping $path — origin/main changed it since checkout ${START_SHA:0:12}" >&2
    fi
  done

  existing=()
  for path in "${ALL_FILES[@]}"; do
    if [ -e "$path" ]; then
      existing+=("$path")
    fi
  done
  git add -- "${existing[@]}"
  if git diff --cached --quiet; then
    echo "No ops monitor artifact delta"
    exit 0
  fi

  git commit -m "$COMMIT_MESSAGE"
  if git push origin HEAD:main; then
    echo "Ops monitor artifacts committed on attempt $attempt"
    exit 0
  fi

  echo "Ops monitor push rejected (attempt $attempt/$MAX_ATTEMPTS); retrying" >&2
  git reset --hard origin/main
  if [ "$attempt" -eq "$MAX_ATTEMPTS" ]; then
    break
  fi
  delay=$((SLEEP_BASE * attempt))
  echo "Retrying in ${delay}s…" >&2
  sleep "$delay"
  attempt=$((attempt + 1))
done

echo "::error::Could not push ops monitor artifacts after $MAX_ATTEMPTS attempts" >&2
exit 1
