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
set -euo pipefail

LANE=""
BUDGET=""
STREAM="1"
LOOP_JSON=""
COMMIT_MESSAGE=""
EXPLORE=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --lane) LANE="$2"; shift 2 ;;
    --budget) BUDGET="$2"; shift 2 ;;
    --stream) STREAM="$2"; shift 2 ;;
    --loop-json) LOOP_JSON="$2"; shift 2 ;;
    --commit-message) COMMIT_MESSAGE="$2"; shift 2 ;;
    --explore) EXPLORE=1; shift ;;
    --) shift; break ;;
    *)
      echo "ingest_hunt_commit: unknown argument $1" >&2
      exit 2
      ;;
  esac
done

if [ -z "$LANE" ] || [ -z "$BUDGET" ] || [ -z "$COMMIT_MESSAGE" ]; then
  echo "ingest_hunt_commit: --lane, --budget, and --commit-message are required" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
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
  bash "$ROOT/scripts/push_library_ingest_artifacts.sh" "$COMMIT_MESSAGE"
  if [ "$(date +%s)" -ge "$deadline" ]; then
    break
  fi
done

if [ "$EXPLORE" = "1" ] && [ "$explore" = "true" ]; then
  ftse-library catalogue-explore --one --json-path /tmp/catalogue_explore.json
  bash "$ROOT/scripts/push_library_ingest_artifacts.sh" \
    "chore: catalogue explorer one name [skip ci]"
  # One pending buy, after the name record is already saved. Then stop.
  ftse-library catalogue-handoff --one --json-path /tmp/catalogue_handoff.json
  bash "$ROOT/scripts/push_library_ingest_artifacts.sh" \
    "chore: catalogue explorer handoff ingest [skip ci]"
fi

ftse-library ingest-hunt-finish \
  --lane "$LANE" \
  --state-path "$STATE_PATH" \
  --json-path /tmp/ingest_hunt_finish.json
bash "$ROOT/scripts/push_library_ingest_artifacts.sh" "$COMMIT_MESSAGE"
