#!/usr/bin/env bash
# Fetch one name, commit the library artifacts, then fetch the next.
#
# A job timeout can drop only the name still in progress. Earlier slices are
# already on main. The budget argument is the existing slot ceiling. This
# script does not raise it.
#
#   ingest_hunt_commit.sh --lane sprint --budget 2100 --stream 2 \
#     --loop-json /tmp/library_ingest_sprint.json \
#     --commit-message 'chore: library ingest sprint [skip ci]' \
#     [--explore] -- [extra ftse-library ingest-hunt-slice args]
#
# Catalogue walk, after the index hunt has already returned. Stream 1 uses
# --catalogue screen. Stream 2 uses --catalogue handoff. The loop stops while
# the 110-minute job can still commit. JOB_START_EPOCH is the job's start.
# An empty handoff queue exits.
#
#   ingest_hunt_commit.sh --catalogue screen --job-seconds 6600 \
#     --commit-reserve 300 \
#     --commit-message 'chore: catalogue explorer one name [skip ci]'
set -euo pipefail

LANE=""
BUDGET=""
STREAM="1"
LOOP_JSON=""
COMMIT_MESSAGE=""
EXPLORE=0
CATALOGUE_MODE=""
JOB_SECONDS=""
COMMIT_RESERVE="300"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --lane) LANE="$2"; shift 2 ;;
    --budget) BUDGET="$2"; shift 2 ;;
    --stream) STREAM="$2"; shift 2 ;;
    --loop-json) LOOP_JSON="$2"; shift 2 ;;
    --commit-message) COMMIT_MESSAGE="$2"; shift 2 ;;
    --explore) EXPLORE=1; shift ;;
    --catalogue) CATALOGUE_MODE="$2"; shift 2 ;;
    --job-seconds) JOB_SECONDS="$2"; shift 2 ;;
    --commit-reserve) COMMIT_RESERVE="$2"; shift 2 ;;
    --) shift; break ;;
    *)
      echo "ingest_hunt_commit: unknown argument $1" >&2
      exit 2
      ;;
  esac
done

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

push_artifacts() {
  local push_script="${PUSH_LIBRARY_SCRIPT:-$ROOT/scripts/push_library_ingest_artifacts.sh}"
  bash "$push_script" "$COMMIT_MESSAGE"
}

read_catalogue_result() {
  JSON_PATH="$1" python3 - <<'PY'
import json
import os
from pathlib import Path

payload = json.loads(Path(os.environ["JSON_PATH"]).read_text(encoding="utf-8"))
print(payload.get("action") or "idle")
print(payload.get("t212_ticker") or payload.get("reason") or "")
PY
}

run_catalogue_loop() {
  local start now deadline window previous json_path action ticker rc
  if [ "$CATALOGUE_MODE" != "screen" ] && [ "$CATALOGUE_MODE" != "handoff" ]; then
    echo "ingest_hunt_commit: --catalogue must be screen or handoff" >&2
    exit 2
  fi
  if [ -z "$COMMIT_MESSAGE" ] || [ -z "$JOB_SECONDS" ]; then
    echo "ingest_hunt_commit: --catalogue requires --job-seconds and --commit-message" >&2
    exit 2
  fi
  if ! [[ "$JOB_SECONDS" =~ ^[0-9]+$ && "$COMMIT_RESERVE" =~ ^[0-9]+$ ]]; then
    echo "ingest_hunt_commit: --job-seconds and --commit-reserve must be whole seconds" >&2
    exit 2
  fi
  start="${JOB_START_EPOCH:-$(date +%s)}"
  if ! [[ "$start" =~ ^[0-9]+$ ]]; then
    echo "ingest_hunt_commit: JOB_START_EPOCH must be a unix time" >&2
    exit 2
  fi
  window="$JOB_SECONDS"
  if [ "$COMMIT_RESERVE" -lt "$window" ]; then
    window=$((window - COMMIT_RESERVE))
  else
    window=0
  fi
  deadline=$((start + window))
  previous=""
  if [ "$CATALOGUE_MODE" = "screen" ]; then
    json_path="/tmp/catalogue_explore.json"
  else
    json_path="/tmp/catalogue_handoff.json"
  fi
  while true; do
    now="$(date +%s)"
    if [ "$now" -ge "$deadline" ]; then
      echo "ingest_hunt_commit: stopping the catalogue ${CATALOGUE_MODE} so the job can commit"
      break
    fi
    set +e
    if [ "$CATALOGUE_MODE" = "screen" ]; then
      ftse-library catalogue-explore --one --json-path "$json_path"
    else
      ftse-library catalogue-handoff --one --json-path "$json_path"
    fi
    rc=$?
    set -e
    if [ "$rc" -ne 0 ]; then
      echo "ingest_hunt_commit: catalogue ${CATALOGUE_MODE} failed rc=$rc" >&2
      exit "$rc"
    fi
    if [ ! -f "$json_path" ]; then
      echo "ingest_hunt_commit: catalogue ${CATALOGUE_MODE} did not write $json_path" >&2
      exit 1
    fi
    mapfile -t lines < <(read_catalogue_result "$json_path")
    action="${lines[0]:-idle}"
    ticker="${lines[1]:-}"
    if [ "$action" != "ran" ]; then
      echo "ingest_hunt_commit: catalogue ${CATALOGUE_MODE} ${action} ${ticker}"
      break
    fi
    if [ -n "$previous" ] && [ "$ticker" = "$previous" ]; then
      echo "ingest_hunt_commit: catalogue repeated ${ticker} — stopping" >&2
      exit 1
    fi
    previous="$ticker"
    echo "ingest_hunt_commit: catalogue ${CATALOGUE_MODE} ${ticker}"
    push_artifacts
  done
}

if [ -n "$CATALOGUE_MODE" ]; then
  run_catalogue_loop
  exit 0
fi

if [ -z "$LANE" ] || [ -z "$BUDGET" ] || [ -z "$COMMIT_MESSAGE" ]; then
  echo "ingest_hunt_commit: --lane, --budget, and --commit-message are required" >&2
  exit 2
fi
STATE_PATH="/tmp/ingest_hunt_state.json"
SLICE_PATH="/tmp/ingest_hunt_slice.json"
deadline="$(( $(date +%s) + BUDGET ))"
action="idle"
explore="false"

write_slice_outputs() {
  SLICE_PATH="$SLICE_PATH" LOOP_PATH="$LOOP_JSON" python3 - <<'PY'
import json
import os
from pathlib import Path

payload = json.loads(Path(os.environ["SLICE_PATH"]).read_text(encoding="utf-8"))
loop_path = os.environ.get("LOOP_PATH") or ""
batch = payload.get("loop_batch")
if loop_path and batch is not None:
    Path(loop_path).write_text(json.dumps(batch, indent=2) + "\n", encoding="utf-8")
print(payload.get("action") or "idle")
print("true" if payload.get("explore") else "false")
PY
}

while true; do
  set +e
  ftse-library ingest-hunt-slice \
    --lane "$LANE" \
    --stream "$STREAM" \
    --state-path "$STATE_PATH" \
    --deadline-epoch "$deadline" \
    --json-path "$SLICE_PATH" \
    "$@"
  rc=$?
  set -e
  if [ "$rc" -ne 0 ]; then
    echo "ingest_hunt_commit: slice failed rc=$rc" >&2
    exit "$rc"
  fi
  if [ ! -f "$SLICE_PATH" ]; then
    echo "ingest_hunt_commit: slice did not write $SLICE_PATH" >&2
    exit 1
  fi
  mapfile -t lines < <(write_slice_outputs)
  action="${lines[0]:-idle}"
  explore="${lines[1]:-false}"
  if [ "$action" != "ran" ]; then
    break
  fi
  push_artifacts
  if [ "$(date +%s)" -ge "$deadline" ]; then
    break
  fi
done

catalogue_explore="false"
if [ "$EXPLORE" = "1" ] && [ "$explore" = "true" ]; then
  catalogue_explore="true"
fi
if [ -n "${GITHUB_OUTPUT:-}" ]; then
  echo "catalogue_explore=${catalogue_explore}" >> "$GITHUB_OUTPUT"
fi

ftse-library ingest-hunt-finish \
  --lane "$LANE" \
  --state-path "$STATE_PATH" \
  --json-path /tmp/ingest_hunt_finish.json
push_artifacts
