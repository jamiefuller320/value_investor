#!/usr/bin/env bash
# Monitor FTSE ingest body-gap catch-up and dispatch the next deepen batch
# until buy-tier indexed_without_body is at/under TARGET (default 0).
#
# Usage:
#   WORKFLOW_DISPATCH_PAT=… ./scripts/monitor_ingest_body_drain.sh
#   ./scripts/monitor_ingest_body_drain.sh --status-only
#   ./scripts/monitor_ingest_body_drain.sh --dispatch-if-idle
#
# Env:
#   TARGET_INDEXED_WITHOUT_BODY  default 0
#   MAX_TARGETS / MAX_BODIES / MAX_RUNTIME_SECONDS / MAX_DRAIN_GENERATIONS
#   REPO  default jamiefuller320/value_investor
set -euo pipefail

REPO="${REPO:-jamiefuller320/value_investor}"
TARGET="${TARGET_INDEXED_WITHOUT_BODY:-0}"
MAX_TARGETS="${MAX_TARGETS:-62}"
MAX_BODIES="${MAX_BODIES:-40}"
MAX_RUNTIME_SECONDS="${MAX_RUNTIME_SECONDS:-3600}"
MAX_DRAIN_GENERATIONS="${MAX_DRAIN_GENERATIONS:-12}"
STATUS_ONLY=0
DISPATCH_IF_IDLE=0

for arg in "$@"; do
  case "$arg" in
    --status-only) STATUS_ONLY=1 ;;
    --dispatch-if-idle) DISPATCH_IF_IDLE=1 ;;
    -h|--help)
      sed -n '1,20p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown arg: $arg" >&2
      exit 2
      ;;
  esac
done

if [[ -n "${WORKFLOW_DISPATCH_PAT:-}" ]]; then
  export GH_TOKEN="$WORKFLOW_DISPATCH_PAT"
fi

json_health() {
  gh api "repos/${REPO}/contents/docs/data/ingest_health_log.json?ref=main" \
    --jq '.content' | base64 -d | python3 -c '
import json, sys
d = json.load(sys.stdin)
entries = d.get("entries") or []
if not entries:
    print(json.dumps({"error": "no health entries"}))
    raise SystemExit(0)
e = entries[-1]
ha = e.get("health_after") or {}
print(json.dumps({
    "run_at": e.get("run_at"),
    "source": e.get("source"),
    "indexed_without_body": int(ha.get("indexed_without_body") or 0),
    "filings_with_body": ha.get("filings_with_body"),
    "zero_body_buy_tier": ha.get("zero_body_buy_tier"),
    "targets_planned": e.get("targets_planned"),
    "targets_completed": e.get("targets_completed"),
    "ingest_improved": e.get("ingest_improved"),
    "runtime_cutoff": e.get("runtime_cutoff"),
}))
'
}

active_runs() {
  gh run list --repo "$REPO" --workflow=ingest-loop.yml --limit 10 \
    --json databaseId,status,conclusion,createdAt,url,event \
    --jq '[.[] | select(.status=="in_progress" or .status=="queued" or .status=="pending" or .status=="waiting")]'
}

health="$(json_health)"
active="$(active_runs)"
active_count="$(python3 -c 'import json,sys; print(len(json.load(sys.stdin)))' <<<"$active")"
gaps="$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("indexed_without_body", -1))' <<<"$health")"

echo "health=$health"
echo "active_ingest_runs=$active_count"
echo "target_indexed_without_body=$TARGET"

if [[ "$STATUS_ONLY" -eq 1 ]]; then
  if [[ "$gaps" -le "$TARGET" ]]; then
    echo "caught_up=true"
  else
    echo "caught_up=false"
  fi
  exit 0
fi

if [[ "$gaps" -le "$TARGET" ]]; then
  echo "caught_up=true — no dispatch"
  exit 0
fi

if [[ "$active_count" -gt 0 ]]; then
  echo "caught_up=false — ingest already running; not dispatching"
  echo "$active" | python3 -m json.tool
  exit 0
fi

if [[ "$DISPATCH_IF_IDLE" -ne 1 ]]; then
  echo "caught_up=false — pass --dispatch-if-idle to start next batch"
  exit 0
fi

echo "Dispatching deepen batch (gaps=$gaps > target=$TARGET)"
gh workflow run ingest-loop.yml --repo "$REPO" \
  -f max_targets="$MAX_TARGETS" \
  -f max_bodies="$MAX_BODIES" \
  -f max_runtime_seconds="$MAX_RUNTIME_SECONDS" \
  -f force=true \
  -f drain_generation=1 \
  -f max_drain_generations="$MAX_DRAIN_GENERATIONS"
echo "dispatched=true"
